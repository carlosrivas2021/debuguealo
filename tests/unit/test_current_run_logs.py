import io
import re
import struct
from decimal import Decimal
from types import SimpleNamespace

import pytest
from docker.errors import APIError

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import LogEntry
from debugpilot.docker import worker
from debugpilot.docker.service import DockerService
from debugpilot.storage.config import Settings

START = "2026-10-28T20:00:00.123456789Z"
OLD = "2026-10-28T20:00:00.123456788Z"
START_SINCE = "1793217600.123456789"


def install_worker(monkeypatch, started=START):
    requests, emitted = [], []

    class API:
        def _url(self, route):
            return route

        def _raise_for_status(self, response):
            pass

        def _get(self, route, *, params, **_kwargs):
            requests.append(params.copy())
            records = [(OLD, "previous execution"), (START, "startup")]
            since = params.get("since")
            if since is not None:
                # The daemon parses Unix seconds.nanoseconds, not CLI date syntax.
                if not re.fullmatch(r"\d+(?:\.\d{1,9})?", str(since)):
                    raise APIError(
                        "Invalid since timestamp", response=SimpleNamespace(status_code=500)
                    )
                records = [
                    record
                    for record, epoch in zip(
                        records,
                        (Decimal("1793217600.123456788"), Decimal(START_SINCE)),
                        strict=True,
                    )
                    if epoch >= Decimal(str(since))
                ]
            data = b""
            for timestamp, message in records:
                line = f"{timestamp} {message}\n".encode()
                data += struct.pack(">BxxxI", 1, len(line)) + line
            return io.BytesIO(data)

    # read_frames consumes response.raw, while the response owns its lifetime.
    original_get = API._get

    class Response:
        def __init__(self, raw):
            self.raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.raw.close()

    monkeypatch.setattr(
        API, "_get", lambda self, *args, **kwargs: Response(original_get(self, *args, **kwargs))
    )
    monkeypatch.setattr(
        worker.docker,
        "DockerClient",
        lambda **_kwargs: SimpleNamespace(api=API(), close=lambda: None),
    )
    monkeypatch.setattr(
        worker,
        "bounded_json",
        lambda _api, route: (
            {"ApiVersion": "1.41"}
            if route == "/version"
            else {"Config": {"Tty": False}, "State": {"StartedAt": started}}
        ),
    )
    monkeypatch.setattr(worker, "emit", lambda kind, **values: emitted.append((kind, values)))
    return requests, emitted


@pytest.mark.parametrize("since", [None, 1_000_000_000])
def test_worker_current_run_uses_exact_start_even_when_replay_overlaps(monkeypatch, since):
    requests, emitted = install_worker(monkeypatch)
    worker.run(
        Settings(),
        {
            "command": "logs",
            "container": "api",
            "tail": 100,
            "follow": False,
            "since": since,
            "current_run": True,
        },
    )
    assert requests[0]["since"] == START_SINCE
    assert [value["value"]["text"] for kind, value in emitted if kind == "log"] == ["startup"]
    assert not [value for kind, value in emitted if kind == "error"]


@pytest.mark.parametrize(
    "started,expected",
    [
        ("2026-10-28T20:00:00Z", "1793217600.000000000"),
        ("2026-10-28T20:00:00.1Z", "1793217600.100000000"),
        ("2026-10-28T20:00:00.000000001Z", "1793217600.000000001"),
        ("2026-10-28T17:00:00.123456789-03:00", START_SINCE),
        ("2026-10-29T01:30:00.123456789+05:30", START_SINCE),
    ],
)
def test_current_run_http_timestamp_preserves_fraction_and_timezone(monkeypatch, started, expected):
    requests, emitted = install_worker(monkeypatch, started)
    worker.run(
        Settings(),
        {
            "command": "logs",
            "container": "api",
            "tail": 100,
            "follow": False,
            "current_run": True,
        },
    )
    assert requests[0]["since"] == expected
    assert not [value for kind, value in emitted if kind == "error"]


def test_current_run_keeps_a_later_replay_cursor(monkeypatch):
    requests, emitted = install_worker(monkeypatch)
    worker.run(
        Settings(),
        {
            "command": "logs",
            "container": "api",
            "tail": 100,
            "follow": False,
            "current_run": True,
            "since": 1793217601,
        },
    )
    assert requests[0]["since"] == 1793217601
    assert not [value for kind, value in emitted if kind == "error"]


def test_worker_default_still_returns_history(monkeypatch):
    requests, emitted = install_worker(monkeypatch)
    worker.run(Settings(), {"command": "logs", "container": "api", "tail": 10, "follow": False})
    assert "since" not in requests[0] and requests[0]["tail"] == 10
    assert [value["value"]["text"] for kind, value in emitted if kind == "log"] == [
        "previous execution",
        "startup",
    ]


@pytest.mark.parametrize("started", [None, "invalid", "0001-01-01T00:00:00Z"])
def test_unknown_execution_never_falls_back_to_history(monkeypatch, started):
    requests, emitted = install_worker(monkeypatch, started)
    worker.run(
        Settings(),
        {"command": "logs", "container": "api", "tail": 100, "follow": False, "current_run": True},
    )
    assert not requests
    assert not [value for kind, value in emitted if kind == "log"]


async def test_current_run_option_reaches_worker_without_changing_default_requests(monkeypatch):
    requests = []

    async def records(_self, request):
        requests.append(request)
        yield {"kind": "log", "value": LogEntry(text="startup").model_dump(mode="json")}

    monkeypatch.setattr(DockerService, "_records", records)
    async with DebugPilotEngine(Settings(), docker=DockerService(Settings())) as engine:
        for options in ({}, {"current_run": True}):
            assert [e.text async for e in engine.stream_logs("api", **options)] == ["startup"]
    assert requests[0] == {
        "command": "logs",
        "container": "api",
        "tail": 100,
        "follow": False,
        "since": None,
    }
    assert requests[1] == {**requests[0], "current_run": True}


async def test_default_engine_call_preserves_legacy_provider_signature():
    class Provider:
        async def stream_logs(self, container, *, tail=100, follow=False):
            assert (container, tail, follow) == ("api", 10, False)
            yield LogEntry(text="history")

    async with DebugPilotEngine(Settings(), docker=Provider()) as engine:
        assert [e.text async for e in engine.stream_logs("api", tail=10)] == ["history"]
