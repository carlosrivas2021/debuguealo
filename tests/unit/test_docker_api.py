import pytest

from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import ContainerInfo, LogEntry
from debugpilot.docker.service import DockerService
from debugpilot.storage.config import Settings


def entry(text="hello", timestamp="2026-10-26T18:00:00.123456789Z", stream="stdout"):
    return LogEntry(timestamp=timestamp, stream=stream, text=text)


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
