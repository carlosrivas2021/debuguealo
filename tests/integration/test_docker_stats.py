"""Real Docker stats through the persistent worker; skipped without Docker."""

import asyncio
import uuid

import pytest
from test_tui_real_logs import docker

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import cpu_percent
from debugpilot.docker.diagnostics import DockerDiagnostics
from debugpilot.docker.service import DockerService
from debugpilot.storage.config import Settings

BUSY = "x = 0\nwhile True:\n    x += 1\n"


async def test_real_stats_give_cpu_and_memory_for_a_running_container():
    settings = Settings()
    if (await DockerDiagnostics(settings).inspect())[0].status != "ok":
        pytest.skip("docker is not available")
    name = f"debugealo-test-stats-{uuid.uuid4().hex[:12]}"
    code, output = await docker("run", "-d", "--rm", "--name", name,
                                "python:3.12-alpine", "python", "-c", BUSY)
    assert code == 0, output
    try:
        async with DebugPilotEngine(settings, docker=DockerService(settings)) as engine:
            first = await engine.container_stats(name)
            await asyncio.sleep(1.5)
            second = await engine.container_stats(name)
            assert second.memory_usage and second.memory_usage > 0
            assert second.memory_limit and second.memory_limit >= second.memory_usage
            percent = cpu_percent(first, second)
            # A busy loop uses close to one CPU.
            assert percent is not None and percent > 10
    finally:
        await docker("rm", "-f", name)


async def test_real_stats_of_a_stopped_container_have_no_values():
    settings = Settings()
    if (await DockerDiagnostics(settings).inspect())[0].status != "ok":
        pytest.skip("docker is not available")
    name = f"debugealo-test-stats-{uuid.uuid4().hex[:12]}"
    code, output = await docker("create", "--name", name, "python:3.12-alpine", "true")
    assert code == 0, output
    try:
        async with DebugPilotEngine(settings, docker=DockerService(settings)) as engine:
            stats = await engine.container_stats(name)
            assert (stats.memory_usage, stats.system_cpu) == (None, None)
    finally:
        await docker("rm", "-f", name)
