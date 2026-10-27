import asyncio
import json
import os
import sys
from contextlib import aclosing, asynccontextmanager
from pathlib import Path

import pytest

from debugpilot.core.exceptions import DockerError
from debugpilot.docker.diagnostics import DockerDiagnostics, default_endpoint
from debugpilot.docker.service import DockerService
from debugpilot.storage.config import Settings

pytestmark = pytest.mark.integration


async def require_docker():
    checks = await DockerDiagnostics(Settings()).inspect()
    if checks[0].status != "ok":
        pytest.skip(checks[0].detail)


async def test_real_inventory_and_stopped_container_history():
    await require_docker()
    service = DockerService(Settings())
    inventory = await service.list_containers()
    assert len({item.id for item in inventory}) == len(inventory)
    assert all(item.name and item.created_at.tzinfo is not None for item in inventory)
    for container in inventory:
        try:
            async with aclosing(service.stream_logs(container.id, tail=2)) as source:
                records = [entry async for entry in source]
        except DockerError:
            continue  # Some drivers deliberately do not retain container logs.
        if records:
            assert all(
                entry.timestamp and entry.stream in {"stdout", "stderr", "combined"}
                for entry in records
            )
            if container.state == "exited":
                async with asyncio.timeout(10):
                    async with aclosing(
                        service.stream_logs(container.id, tail=0, follow=True)
                    ) as source:
                        assert [entry async for entry in source] == []
            return
    pytest.skip("Inventory verified, but no existing readable retained log records were available.")


@asynccontextmanager
async def log_fixture(tmp_path):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR"}
    }
    environment.update(DOCKER_CONFIG=str(tmp_path), PYTHONUTF8="1")
    helper = Path(__file__).parents[1] / "fixtures" / "docker_log_source.py"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(helper),
        default_endpoint(),
        cwd=tmp_path,
        env=environment,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **({"creationflags": 0x08000000} if os.name == "nt" else {}),
    )
    try:
        async with asyncio.timeout(15):
            line = await process.stdout.readline()
        if not line:
            error = (await process.stderr.read(4096)).decode(errors="replace")
            pytest.fail(f"Docker log fixture failed: {error}")
        result = json.loads(line)
        if "skip" in result:
            pytest.skip(result["skip"])
        yield result["id"]
    finally:
        process.stdin.close()
        async with asyncio.timeout(15):
            await process.wait()
        assert process.returncode == 0, "Docker fixture cleanup failed"


async def test_real_follow_channels_and_cancel_cleanup(tmp_path):
    await require_docker()
    async with log_fixture(tmp_path) as container:
        entries = []
        service = DockerService(Settings())
        async with aclosing(service.stream_logs(container, tail=100, follow=True)) as source:
            async with asyncio.timeout(15):
                async for entry in source:
                    entries.append(entry)
                    if entry.text == "INFO debugpilot-later":
                        break
        assert [entry.text for entry in entries if entry.stream == "stdout"] == [
            "INFO debugpilot-start",
            "INFO debugpilot-later",
        ]
        errors = [entry for entry in entries if entry.stream == "stderr"]
        assert len(errors) == 1 and errors[0].text == "ERROR debugpilot-stderr"
        assert errors[0].severity == "error"
        assert all(entry.timestamp and not entry.truncated for entry in entries)
