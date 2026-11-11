import asyncio
import io
import json
import struct
from contextlib import aclosing

import pytest
from typer.testing import CliRunner

from debugpilot import __version__
from debugpilot.cli import app
from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import ContainerInfo, LogEntry
from debugpilot.docker.logs import LogBuffer, LogDecoder, ReplayCursor, read_frames
from debugpilot.docker.service import DockerService
from debugpilot.storage.config import Settings


def entry(text="hello", timestamp="2026-10-26T18:00:00.123456789Z", stream="stdout"):
    return LogEntry(timestamp=timestamp, stream=stream, text=text)


def inventory_from(records):
    """Serve the inventory from the same fake records as the one-shot worker."""

    async def inventory(self):
        return [record async for record in records(self, {"command": "containers"})]

    return inventory


def test_container_metadata_and_compose_labels():
    container = ContainerInfo.from_docker(
        {
            "Id": "abc123",
            "Names": ["/payments-api"],
            "Image": "payments:dev",
            "State": "exited",
            "Created": 1_700_000_000,
            "Ports": [{"PrivatePort": 8000, "PublicPort": 8080, "IP": "127.0.0.1", "Type": "tcp"}],
            "Labels": {
                "com.docker.compose.project": "demo",
                "com.docker.compose.service": "payments",
            },
        }
    )
    assert container.name == "payments-api"
    assert container.state == "exited"
    assert container.compose_project == "demo"
    assert container.compose_service == "payments"
    assert container.ports[0].public_port == 8080
    assert container.created_at.year == 2023


def test_plain_docker_container_without_compose_or_published_ports():
    container = ContainerInfo.from_docker({"Id": "abc", "Image": "demo", "Created": 0})
    assert container.name == "abc"
    assert container.compose_project is None
    assert container.ports == ()


@pytest.mark.parametrize("ports", [None, []])
def test_container_metadata_accepts_null_or_empty_ports(ports):
    container = ContainerInfo.from_docker(
        {
            "Id": "abc",
            "Names": ["/catalog-worker"],
            "Image": "catalog:local",
            "State": "running",
            "Created": 1_700_000_000,
            "Ports": ports,
            "Labels": {"com.docker.compose.project": "dp-demo-catalog"},
        }
    )
    assert container.ports == ()
    assert container.name == "catalog-worker"
    assert container.state == "running"
    assert container.compose_project == "dp-demo-catalog"


def test_frame_decoder_preserves_stdout_stderr_and_rejects_oversized_or_truncated():
    def frame(stream, data):
        return struct.pack(">BxxxI", stream, len(data)) + data

    raw = frame(1, b"a\n") + frame(2, b"b\n")
    assert list(read_frames(io.BytesIO(raw), tty=False)) == [("stdout", b"a\n"), ("stderr", b"b\n")]
    for raw in (b"short", struct.pack(">BxxxI", 1, 2_000_000), frame(1, b"long")[:-1]):
        with pytest.raises(DockerError):
            list(read_frames(io.BytesIO(raw), tty=False))
    assert list(read_frames(io.BytesIO(b"tty\n"), tty=True)) == [("combined", b"tty\n")]


def test_log_decoder_handles_partial_utf8_and_infers_severity():
    decoder = LogDecoder(max_line_bytes=100)
    raw = "2026-10-26T18:00:00.123456789Z ERROR café\n".encode()
    assert decoder.feed("stderr", raw[:-2]) == []
    logs = decoder.feed("stderr", raw[-2:])
    assert len(logs) == 1
    assert logs[0].text == "ERROR café"
    assert logs[0].timestamp.endswith("123456789Z")
    assert logs[0].severity == "error"
    assert logs[0].stream == "stderr"


def test_oversized_line_is_truncated_once_and_memory_is_bounded():
    decoder = LogDecoder(max_line_bytes=64)
    logs = decoder.feed("stdout", b"x" * 100_000)
    assert len(logs) == 1 and logs[0].truncated
    assert len(logs[0].text) <= 64
    assert decoder.buffered_bytes <= 64
    assert decoder.feed("stdout", b"more\nnext\n")[0].text == "next"


def test_ring_buffer_bounds_entries_bytes_and_filters():
    buffer = LogBuffer(max_entries=2, max_bytes=100)
    buffer.append(entry("first"))
    buffer.append(entry("INFO second"))
    buffer.append(entry("ERROR third").model_copy(update={"severity": "error"}))
    assert [log.text for log in buffer.entries()] == ["INFO second", "ERROR third"]
    assert [log.text for log in buffer.entries(text="third", severity="error")] == ["ERROR third"]
    assert buffer.byte_size <= 100
    buffer.clear()
    assert buffer.entries() == () and buffer.byte_size == 0


def test_reconnect_replay_preserves_legitimate_duplicate_multiplicity():
    cursor = ReplayCursor(capacity=4)
    assert cursor.accept(entry("same"))
    assert cursor.accept(entry("same"))
    cursor.reconnecting()
    assert cursor.since is not None
    assert not cursor.accept(entry("same"))
    assert not cursor.accept(entry("same"))
    assert cursor.accept(entry("same"))  # A new third identical record must survive.
    assert cursor.accept(entry("next", "2026-10-26T18:00:01.000000001Z"))


def test_reconnect_without_timestamps_or_beyond_window_fails_explicitly():
    for values in ([entry(timestamp=None)], [entry("a"), entry("b")]):
        cursor = ReplayCursor(capacity=1)
        for value in values:
            cursor.accept(value)
        with pytest.raises(DockerError):
            cursor.reconnecting()


def test_initial_stdout_stderr_time_skew_does_not_drop_records():
    cursor = ReplayCursor()
    assert cursor.accept(entry("stderr first", "2026-10-26T18:00:01.000000001Z", "stderr"))
    assert cursor.accept(entry("delayed stdout", "2026-10-26T18:00:00.999999999Z"))


async def test_discovery_and_history_use_worker_records(monkeypatch):
    requests = []

    async def records(_self, request):
        requests.append(request)
        if request["command"] == "containers":
            yield {
                "kind": "container",
                "value": ContainerInfo.from_docker({"Id": "abc"}).model_dump(mode="json"),
            }
        else:
            yield {"kind": "log", "value": entry().model_dump(mode="json")}

    monkeypatch.setattr(DockerService, "_records", records)
    monkeypatch.setattr(DockerService, "_inventory_records", inventory_from(records))
    service = DockerService(Settings())
    assert (await service.list_containers())[0].id == "abc"
    assert [log.text async for log in service.stream_logs("abc", tail=10)] == ["hello"]
    assert requests[-1]["tail"] == 10 and requests[-1]["follow"] is False


async def test_stream_reconnect_resumes_and_deduplicates(monkeypatch):
    calls = []

    async def records(_self, request):
        calls.append(request.copy())
        yield {"kind": "log", "value": entry().model_dump(mode="json")}
        if len(calls) == 1:
            raise DockerError("Disconnected", retryable=True)
        yield {"kind": "log", "value": entry("later").model_dump(mode="json")}

    monkeypatch.setattr(DockerService, "_records", records)
    service = DockerService(Settings(), reconnect_delay=0)
    assert [log.text async for log in service.stream_logs("abc", follow=True)] == ["hello", "later"]
    assert calls[1]["since"] is not None


async def test_engine_close_cancels_stream_and_reaps_provider():
    started = asyncio.Event()
    closed = asyncio.Event()

    class Provider:
        async def stream_logs(self, *_args, **_kwargs):
            try:
                started.set()
                yield entry()
                await asyncio.Event().wait()
            finally:
                closed.set()

    async with DebugPilotEngine(Settings(), docker=Provider()) as engine:
        async with aclosing(engine.stream_logs("abc", follow=True)) as stream:
            assert (await anext(stream)).text == "hello"
            await asyncio.wait_for(started.wait(), 2)
            await engine.close()
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(stream), 2)
    assert closed.is_set()


async def test_engine_backpressure_does_not_drop_final_historical_entries():
    class Provider:
        async def stream_logs(self, *_args, **_kwargs):
            for number in range(512):
                yield entry(str(number))

    async with DebugPilotEngine(Settings(), docker=Provider()) as engine:
        async with aclosing(engine.stream_logs("abc")) as stream:
            values = [log.text async for log in stream]
    assert values == [str(number) for number in range(512)]


async def test_engine_delivers_buffered_records_before_producer_error():
    class Provider:
        async def stream_logs(self, *_args, **_kwargs):
            for number in range(512):
                yield entry(str(number))
            raise DockerError("Log stream failed.")

    values = []
    async with DebugPilotEngine(Settings(), docker=Provider()) as engine:
        async with aclosing(engine.stream_logs("abc")) as stream:
            with pytest.raises(DockerError, match="Log stream failed"):
                async for log in stream:
                    values.append(log.text)
    assert values == [str(number) for number in range(512)]


@pytest.mark.parametrize("retryable, expected_calls", [(True, 4), (False, 1)])
async def test_follow_retry_budget_and_terminal_errors(monkeypatch, retryable, expected_calls):
    calls = 0

    async def records(_self, _request):
        nonlocal calls
        calls += 1
        raise DockerError("Unavailable.", retryable=retryable)
        yield  # Keep the worker mock an async iterator.

    monkeypatch.setattr(DockerService, "_records", records)
    with pytest.raises(DockerError, match="Unavailable"):
        _ = [
            log
            async for log in DockerService(Settings(), reconnect_delay=0).stream_logs(
                "abc", follow=True
            )
        ]
    assert calls == expected_calls


@pytest.mark.parametrize("container,tail", [("../secret", 10), ("abc", -1), ("abc", 10001)])
async def test_invalid_log_inputs_never_spawn_worker(monkeypatch, container, tail):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Worker should not start")

    monkeypatch.setattr(DockerService, "_records", forbidden)
    with pytest.raises(ValueError):
        _ = [log async for log in DockerService(Settings()).stream_logs(container, tail=tail)]


def test_container_and_logs_cli(monkeypatch):
    async def records(_self, request):
        if request["command"] == "containers":
            yield {
                "kind": "container",
                "value": ContainerInfo.from_docker(
                    {"Id": "abc", "Names": ["/demo"], "Labels": {"long": "x" * 300}}
                ).model_dump(mode="json"),
            }
        else:
            yield {"kind": "log", "value": entry("INFO from container").model_dump(mode="json")}

    monkeypatch.setattr(DockerService, "_records", records)
    monkeypatch.setattr(DockerService, "_inventory_records", inventory_from(records))
    runner = CliRunner()
    result = runner.invoke(app, ["containers"])
    assert result.exit_code == 0 and "demo" in result.output
    result = runner.invoke(app, ["containers", "--json"])
    assert result.exit_code == 0 and json.loads(result.output)[0]["name"] == "demo"
    result = runner.invoke(app, ["logs", "demo", "--tail", "10"])
    assert result.exit_code == 0 and "INFO from container" in result.output
    assert runner.invoke(app, ["logs", "demo", "--tail", "-1"]).exit_code == 2
    assert runner.invoke(app, ["version"]).output.strip() == f"debugealo {__version__}"
