import asyncio
from types import SimpleNamespace

import pytest
from docker.errors import APIError

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import DockerError, LifecycleError
from debugpilot.core.models import StopResult
from debugpilot.docker import service as docker_service
from debugpilot.docker import worker
from debugpilot.docker.service import DockerService
from debugpilot.storage.config import Settings


async def test_stop_requires_exact_confirmation_and_valid_bounded_targets(monkeypatch):
    calls = []

    async def records(_self, request):
        calls.append(request)
        yield {"kind": "stop_result", "container": request["containers"][0], "stopped": True}

    monkeypatch.setattr(DockerService, "_records", records)
    service = DockerService(Settings())
    for confirmed in (False, 1, "true"):
        with pytest.raises(DockerError, match="confirmation"):
            await service.stop_containers(("container-a",), confirmed=confirmed)
    for containers in (
        (),
        ("container-a", "container-a"),
        ("--all",),
        ("bad/name",),
        tuple(f"container-{index}" for index in range(33)),
        "container-a",
    ):
        with pytest.raises((DockerError, ValueError)):
            await service.stop_containers(containers, confirmed=True)
    for timeout in (True, False, 0, 31, "10"):
        with pytest.raises(DockerError, match="timeout"):
            await service.stop_containers(("container-a",), confirmed=True, timeout_seconds=timeout)
    assert not calls


async def test_stop_request_pins_literal_targets_and_propagates_grace(monkeypatch):
    requests = []
    targets = ("a" * 64, "worker-1")

    async def records(_self, request):
        requests.append(request)
        for target in request["containers"]:
            yield {"kind": "stop_result", "container": target, "stopped": True}

    monkeypatch.setattr(DockerService, "_records", records)
    result = await DockerService(Settings()).stop_containers(
        targets, confirmed=True, timeout_seconds=17
    )
    assert result == StopResult(stopped=targets, failed={})
    assert requests == [{"command": "stop", "containers": list(targets), "timeout_seconds": 17}]


async def test_stop_preserves_partial_results_and_bounds_failure_messages(monkeypatch):
    async def records(_self, request):
        yield {
            "kind": "stop_result",
            "container": request["containers"][0],
            "stopped": True,
        }
        yield {
            "kind": "stop_result",
            "container": request["containers"][1],
            "stopped": False,
            "message": "secret daemon response" * 100,
        }

    monkeypatch.setattr(DockerService, "_records", records)
    result = await DockerService(Settings()).stop_containers(("api", "worker"), confirmed=True)
    assert result.stopped == ("api",)
    assert result.failed == {"worker": "Stop outcome unknown; inspect container state."}


async def test_stop_transport_interruption_marks_only_unreported_targets_unknown(monkeypatch):
    async def records(_self, _request):
        yield {"kind": "stop_result", "container": "api", "stopped": True}
        raise DockerError("Docker worker disconnected.")

    monkeypatch.setattr(DockerService, "_records", records)
    result = await DockerService(Settings()).stop_containers(
        ("api", "worker", "cache"), confirmed=True
    )
    assert result.stopped == ("api",)
    assert result.failed == {
        "worker": "Stop outcome unknown; inspect container state.",
        "cache": "Stop outcome unknown; inspect container state.",
    }


async def test_stop_cancellation_propagates_and_reaps_worker(monkeypatch):
    started = asyncio.Event()
    reaped = asyncio.Event()

    async def records(_self, _request):
        try:
            started.set()
            await asyncio.Event().wait()
            yield {}
        finally:
            reaped.set()

    monkeypatch.setattr(DockerService, "_records", records)
    task = asyncio.create_task(DockerService(Settings()).stop_containers(("api",), confirmed=True))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert reaped.is_set()


async def test_engine_stop_uses_lifecycle_spawn_and_rejects_closed_engine():
    class Provider:
        def __init__(self):
            self.calls = []

        async def stop_containers(self, containers, **kwargs):
            self.calls.append((containers, kwargs))
            return StopResult(stopped=containers, failed={})

    provider = Provider()
    engine = DebugPilotEngine(Settings(), docker=provider)
    with pytest.raises(LifecycleError):
        await engine.stop_containers(("api",), confirmed=True)
    await engine.start()
    assert await engine.stop_containers(("api",), confirmed=True, timeout_seconds=4) == StopResult(
        stopped=("api",), failed={}
    )
    await engine.close()
    with pytest.raises(LifecycleError):
        await engine.stop_containers(("api",), confirmed=True)
    assert provider.calls == [(("api",), {"confirmed": True, "timeout_seconds": 4})]


async def test_engine_close_cancels_stop_provider_and_waits_for_cleanup():
    started = asyncio.Event()
    cleaned = asyncio.Event()

    class Provider:
        async def stop_containers(self, *_args, **_kwargs):
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()

    engine = DebugPilotEngine(Settings(), docker=Provider())
    await engine.start()
    request = asyncio.create_task(engine.stop_containers(("api",), confirmed=True))
    await asyncio.wait_for(started.wait(), 1)
    await engine.close()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert cleaned.is_set()


def test_worker_stop_calls_sdk_once_per_pinned_target_and_sanitizes_failures(monkeypatch):
    calls = []

    class API:
        trust_env = True
        _version = None

        def stop(self, container, timeout=None):
            calls.append((container, timeout))
            if container == "missing":
                raise APIError("secret response", response=SimpleNamespace(status_code=404))

    api = API()

    class Client:
        def __init__(self):
            self.api = api
            self.closed = False

        def close(self):
            self.closed = True

    client = Client()
    emitted = []
    monkeypatch.setattr(worker.docker, "DockerClient", lambda **_kwargs: client)
    monkeypatch.setattr(worker, "bounded_json", lambda *_args, **_kwargs: {"ApiVersion": "1.41"})
    monkeypatch.setattr(worker, "emit", lambda kind, **values: emitted.append((kind, values)))
    worker.run(
        Settings(),
        {"command": "stop", "containers": ["api", "missing"], "timeout_seconds": 12},
    )
    assert calls == [("api", 12), ("missing", 12)]
    assert emitted[0] == ("ready", {})
    assert emitted[1] == (
        "stop_result",
        {"container": "api", "stopped": True},
    )
    assert emitted[2] == (
        "stop_result",
        {"container": "missing", "stopped": False, "message": "Container not found."},
    )
    assert client.closed and api.trust_env is False


async def test_records_stop_timeout_includes_grace_margin_without_changing_existing_timeout(
    monkeypatch,
):
    service = DockerService(Settings(docker_timeout_seconds=3))
    captured = {}
    timeouts = []
    timeout = docker_service.asyncio.timeout

    def record_timeout(seconds):
        timeouts.append(seconds)
        return timeout(seconds)

    class Stream:
        async def readline(self):
            return b""

    class Process:
        stdout = Stream()
        returncode = 0

        async def wait(self):
            return 0

    async def create(*_args, **kwargs):
        captured.update(kwargs)
        return Process()

    monkeypatch.setattr(docker_service.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(docker_service.asyncio, "timeout", record_timeout)
    async for _ in service._records(
        {"command": "stop", "containers": ["api"], "timeout_seconds": 20}
    ):
        pass
    async for _ in service._records({"command": "containers"}):
        pass
    assert timeouts == [29, 3, 9, 3]
    assert captured["limit"] == 262_144
