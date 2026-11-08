"""The container inventory reuses one Docker worker process across refreshes."""

import asyncio
import os

import pytest

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import DockerError
from debugpilot.docker.service import DockerService
from debugpilot.storage.config import Settings

pytestmark = pytest.mark.skipif(os.name == "nt", reason="uses a local Unix socket endpoint")


@pytest.fixture
def spawns(monkeypatch):
    calls = []
    original = asyncio.create_subprocess_exec

    async def counting(*args, **kwargs):
        calls.append(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", counting)
    return calls


def unreachable(tmp_path):
    return Settings(docker_endpoint=f"unix://{tmp_path / 'missing.sock'}", docker_timeout_seconds=1)


async def test_inventory_refreshes_reuse_one_worker_process(tmp_path, spawns):
    service = DockerService(unreachable(tmp_path))
    try:
        for _ in range(3):
            with pytest.raises(DockerError, match="Docker connection failed"):
                await service.list_containers()
        assert len(spawns) == 1
    finally:
        await service.close()


async def test_dead_inventory_worker_is_replaced_on_next_refresh(tmp_path, spawns):
    service = DockerService(unreachable(tmp_path))
    try:
        with pytest.raises(DockerError):
            await service.list_containers()
        process = service._inventory[0]
        process.kill()
        await process.wait()
        with pytest.raises(DockerError, match="Docker connection failed"):
            await service.list_containers()
        assert len(spawns) == 2
    finally:
        await service.close()


async def test_cancelled_refresh_kills_worker_and_close_reaps_it(tmp_path, spawns):
    async def silent(reader, writer):
        await reader.read()  # Accept and never answer, like a stalled daemon.

    socket_path = tmp_path / "stalled.sock"
    server = await asyncio.start_unix_server(silent, path=str(socket_path))
    service = DockerService(
        Settings(docker_endpoint=f"unix://{socket_path}", docker_timeout_seconds=30)
    )
    try:
        refresh = asyncio.create_task(service.list_containers())
        await asyncio.sleep(1)
        process = service._inventory[0]
        refresh.cancel()
        with pytest.raises(asyncio.CancelledError):
            await refresh
        assert process.returncode is not None
        assert service._inventory is None
    finally:
        server.close()
        await service.close()


async def test_engine_close_reaps_the_inventory_worker(tmp_path, spawns):
    service = DockerService(unreachable(tmp_path))
    async with DebugPilotEngine(Settings(), docker=service) as engine:
        with pytest.raises(DockerError):
            await engine.list_containers()
        process = service._inventory[0]
        assert process.returncode is None
    assert process.returncode is not None
    assert service._inventory is None
