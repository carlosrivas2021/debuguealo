import asyncio
import json
import os
import re
import sys
import tempfile
from contextlib import aclosing
from pathlib import Path

from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import ContainerInfo, LogEntry, StopResult
from debugpilot.docker.diagnostics import default_endpoint
from debugpilot.docker.logs import ReplayCursor
from debugpilot.storage.config import Settings

_STOP_TARGET_RE = re.compile(r"(?:[A-Fa-f0-9]{12,64}|[A-Za-z0-9][A-Za-z0-9_.-]{0,127})")
_STOP_FAILURE_MESSAGES = {
    "Container not found.",
    "Docker access denied.",
    "Stop failed. Inspect container state.",
    "Stop outcome unknown; inspect container state.",
}
_STOP_UNKNOWN = "Stop outcome unknown; inspect container state."


class DockerService:
    def __init__(self, settings: Settings, *, reconnect_delay: float = 0.5):
        self.settings = settings
        self.reconnect_delay = reconnect_delay
        # One long-lived worker answers inventory refreshes; logs and stops keep
        # their own short-lived workers.
        self._inventory: tuple[asyncio.subprocess.Process, tempfile.TemporaryDirectory] | None = (
            None
        )
        self._inventory_lock = asyncio.Lock()

    async def _spawn_worker(self, directory: str, argument: str, **pipes):
        (Path(directory) / "config.json").write_text("{}", encoding="utf-8")
        environment = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR"}}
        environment.update(DOCKER_CONFIG=directory, PYTHONUTF8="1")
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "debugpilot.docker.worker",
            self.settings.docker_endpoint or default_endpoint(),
            str(self.settings.docker_timeout_seconds),
            argument,
            env=environment,
            cwd=directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=262_144,
            **pipes,
            **({"creationflags": 0x08000000} if os.name == "nt" else {}),
        )

    async def _inventory_records(self) -> list[dict]:
        """Ask the persistent worker for one inventory, respawning it when needed.

        Any failure, timeout or cancellation mid-request kills the worker, because
        its output stream may no longer line up with the next request.
        """
        async with self._inventory_lock:
            completed = False
            records: list[dict] = []
            error = None
            try:
                if self._inventory is None or self._inventory[0].returncode is not None:
                    await self._close_inventory()
                    directory = tempfile.TemporaryDirectory(prefix="debugpilot-docker-")
                    try:
                        process = await self._spawn_worker(
                            directory.name, "--serve", stdin=asyncio.subprocess.PIPE
                        )
                    except BaseException:
                        directory.cleanup()
                        raise
                    self._inventory = (process, directory)
                process = self._inventory[0]
                assert process.stdin is not None and process.stdout is not None
                process.stdin.write(b'{"command": "containers"}\n')
                await process.stdin.drain()
                while True:
                    async with asyncio.timeout(self.settings.docker_timeout_seconds * 2 + 3):
                        line = await process.stdout.readline()
                    if not line:
                        raise DockerError("Docker worker disconnected.", retryable=True)
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise DockerError("Invalid Docker worker response.")
                    kind = record.get("kind")
                    if kind == "done":
                        break
                    if kind == "error":
                        # Keep reading to "done" so the stream stays aligned.
                        error = DockerError(
                            record["message"], retryable=bool(record.get("retryable"))
                        )
                    elif kind != "ready":
                        records.append(record)
                completed = True
            except (OSError, TimeoutError) as failure:
                raise DockerError(
                    "Docker is unavailable or its worker timed out.", retryable=True
                ) from failure
            except (ValueError, KeyError) as failure:
                raise DockerError("Invalid or oversized Docker worker response.") from failure
            finally:
                if not completed:
                    await self._close_inventory()
            if error is not None:
                raise error
            return records

    async def _close_inventory(self) -> None:
        inventory, self._inventory = self._inventory, None
        if inventory is None:
            return
        process, directory = inventory
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        directory.cleanup()

    async def close(self) -> None:
        """Stop the persistent inventory worker; a later refresh starts a new one."""
        await self._close_inventory()

    async def _records(self, request: dict):
        process = None
        with tempfile.TemporaryDirectory(prefix="debugpilot-docker-") as directory:
            try:
                process = await self._spawn_worker(directory, json.dumps(request))
                ready = False
                assert process.stdout is not None
                while True:
                    if ready and request.get("follow"):
                        timeout = None
                    elif request.get("command") == "stop":
                        timeout = (
                            request["timeout_seconds"]
                            + self.settings.docker_timeout_seconds * 2
                            + 3
                        )
                    else:
                        timeout = self.settings.docker_timeout_seconds * 2 + 3
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
        for record in await self._inventory_records():
            if record.get("kind") != "container" or len(containers) >= 10_000:
                raise DockerError("Invalid or oversized container inventory.")
            containers.append(ContainerInfo.model_validate(record["value"]))
        return sorted(containers, key=lambda container: container.name.casefold())

    async def stop_containers(
        self,
        containers: tuple[str, ...],
        *,
        confirmed: bool = False,
        timeout_seconds: int = 10,
    ) -> StopResult:
        if confirmed is not True:
            raise DockerError("Explicit confirmation is required before stopping containers.")
        if (
            not isinstance(containers, tuple)
            or not 1 <= len(containers) <= 32
            or any(
                not isinstance(container, str) or not _STOP_TARGET_RE.fullmatch(container)
                for container in containers
            )
            or len(set(containers)) != len(containers)
        ):
            raise DockerError("Choose between 1 and 32 unique valid container IDs or names.")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 30
        ):
            raise DockerError("Container stop timeout must be an integer from 1 to 30 seconds.")

        stopped = []
        failed = {}
        reported = set()
        request = {
            "command": "stop",
            "containers": list(containers),
            "timeout_seconds": timeout_seconds,
        }
        try:
            async with aclosing(self._records(request)) as records:
                async for record in records:
                    if (
                        not isinstance(record, dict)
                        or record.get("kind") != "stop_result"
                        or record.get("container") not in containers
                        or record.get("container") in reported
                        or type(record.get("stopped")) is not bool
                    ):
                        raise DockerError("Invalid Docker stop result.")
                    target = record["container"]
                    reported.add(target)
                    if record["stopped"]:
                        stopped.append(target)
                    else:
                        message = record.get("message")
                        failed[target] = (
                            message if message in _STOP_FAILURE_MESSAGES else _STOP_UNKNOWN
                        )
        except asyncio.CancelledError:
            # The daemon may have processed the request before local cancellation.
            # Propagate cancellation; never claim rollback or retry a stop.
            raise
        except (DockerError, OSError, TimeoutError, ValueError, KeyError, TypeError):
            # Results already observed are authoritative; unreported targets are not.
            pass
        for target in containers:
            if target not in reported:
                failed[target] = _STOP_UNKNOWN
        return StopResult(stopped=tuple(stopped), failed=failed)

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
