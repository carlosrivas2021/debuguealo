import asyncio

import pytest

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.events import Event, EventBus
from debugpilot.core.exceptions import ConfigurationError, LifecycleError
from debugpilot.storage.config import Settings, load_settings


def test_config_missing_is_default(tmp_path):
    path = tmp_path / "missing.toml"
    assert load_settings(path) == Settings()
    assert not path.exists()


def test_config_parses_limits_and_rejects_invalid_values(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("event_queue_size = 2\n", encoding="utf-8")
    assert load_settings(path).event_queue_size == 2
    for content in ("event_queue_size = 0", "event_queue_size = '2'", "surprise = true", "["):
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ConfigurationError):
            load_settings(path)


def test_config_errors_do_not_echo_input_secrets(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('event_queue_size = "secret-value"', encoding="utf-8")
    with pytest.raises(ConfigurationError) as error:
        load_settings(path)
    assert "secret-value" not in str(error.value)


async def test_events_are_bounded_and_slow_subscriber_does_not_block():
    bus = EventBus(capacity=2)
    async with bus.subscribe() as subscription:
        for number in range(3):
            bus.publish(Event(kind="progress", message=str(number)))
        assert subscription.dropped == 1
        assert (await subscription.get()).message == "1"
        assert (await subscription.get()).message == "2"
    assert bus.subscriber_count == 0


async def test_engine_cancels_owned_tasks_and_rejects_reuse():
    stopped = asyncio.Event()

    async def worker():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    engine = DebugPilotEngine(Settings())
    with pytest.raises(LifecycleError):
        engine.spawn(worker)
    async with engine:
        task = engine.spawn(worker)
        await asyncio.sleep(0)
        assert not task.done()
    assert stopped.is_set()
    assert task.cancelled()
    await engine.close()
    with pytest.raises(LifecycleError):
        await engine.start()


async def test_worker_error_is_observed_without_leaking_exception_text():
    async def broken():
        raise RuntimeError("secret-token")

    async with DebugPilotEngine(Settings()) as engine:
        async with engine.events.subscribe() as subscription:
            engine.spawn(broken)
            event = await asyncio.wait_for(subscription.get(), timeout=2)
            assert event.kind == "task_failed"
            assert "secret-token" not in event.message
