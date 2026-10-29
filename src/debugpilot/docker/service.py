import asyncio
import json
import os
import re
import sys
import tempfile
from contextlib import aclosing
from pathlib import Path

from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import ContainerInfo, LogEntry
from debugpilot.docker.diagnostics import default_endpoint
from debugpilot.docker.logs import ReplayCursor
from debugpilot.storage.config import Settings


class DockerService:
    def __init__(self, settings: Settings, *, reconnect_delay: float = 0.5):
        self.settings = settings
        self.reconnect_delay = reconnect_delay

    async def _records(self, request: dict):
        process = None
        with tempfile.TemporaryDirectory(prefix="debugpilot-docker-") as directory:
            (Path(directory) / "config.json").write_text("{}", encoding="utf-8")
            environment = {
                k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR"}
            }
            environment.update(DOCKER_CONFIG=directory, PYTHONUTF8="1")
            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "debugpilot.docker.worker",
                    self.settings.docker_endpoint or default_endpoint(),
                    str(self.settings.docker_timeout_seconds),
                    json.dumps(request),
                    env=environment,
                    cwd=directory,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=262_144,
                    **({"creationflags": 0x08000000} if os.name == "nt" else {}),
                )
                ready = False
                assert process.stdout is not None
                while True:
                    timeout = (
                        None
                        if ready and request.get("follow")
                        else self.settings.docker_timeout_seconds * 2 + 3
                    )
                    async with asyncio.timeout(timeout):
                        line = await process.stdout.readline()
                    if not line:
                        break
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise DockerError("Invalid Docker worker response.")
                    if record.get("kind") == "ready":
                        ready = True
                    elif record.get("kind") == "error":
                        raise DockerError(
                            record["message"], retryable=bool(record.get("retryable"))
                        )
                    else:
                        yield record
                async with asyncio.timeout(3):
                    await process.wait()
                if process.returncode != 0:
                    raise DockerError("Docker worker disconnected.", retryable=True)
            except (OSError, TimeoutError) as error:
                raise DockerError(
                    "Docker is unavailable or its worker timed out.", retryable=True
                ) from error
            except (ValueError, KeyError) as error:
                raise DockerError("Invalid or oversized Docker worker response.") from error
            finally:
                if process is not None:
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    await process.wait()

    async def list_containers(self) -> list[ContainerInfo]:
        containers = []
        async with aclosing(self._records({"command": "containers"})) as records:
            async for record in records:
                if record.get("kind") != "container" or len(containers) >= 10_000:
                    raise DockerError("Invalid or oversized container inventory.")
                containers.append(ContainerInfo.model_validate(record["value"]))
        return sorted(containers, key=lambda container: container.name.casefold())

    async def watch_containers(self, interval: float = 2):
        if interval < 0.1:
            raise ValueError("Container refresh interval must be at least 0.1 seconds.")
        previous = None
        while True:
            current = await self.list_containers()
            if current != previous:
                yield current
                previous = current
            await asyncio.sleep(interval)

    async def stream_logs(
        self, container: str, *, tail: int = 100, follow: bool = False, current_run: bool = False
    ):
        container = container.removeprefix("/")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
            raise ValueError("Invalid container name or ID.")
        if not 0 <= tail <= 10_000:
            raise ValueError("Log tail must be between 0 and 10000.")
        cursor = ReplayCursor()
        attempts = 0
        while True:
            request = {
                "command": "logs",
                "container": container,
                "tail": tail,
                "follow": follow,
                "since": cursor.since,
            }
            if current_run:
                request["current_run"] = True
            try:
                async with aclosing(self._records(request)) as records:
                    async for record in records:
                        if record.get("kind") != "log":
                            raise DockerError("Invalid log record from Docker worker.")
                        entry = LogEntry.model_validate(record["value"])
                        if cursor.accept(entry):
                            yield entry
                return  # Normal EOF: a stopped container, not a reconnect loop.
            except DockerError as error:
                if not follow or not error.retryable or attempts >= 3:
                    raise
                cursor.reconnecting()
                await asyncio.sleep(self.reconnect_delay * 2**attempts)
                attempts += 1
