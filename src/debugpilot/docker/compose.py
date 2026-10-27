"""Explicit, confirmation-gated local Compose operations without a shell."""

import asyncio
import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from debugpilot.core.exceptions import DebugPilotError
from debugpilot.docker.diagnostics import default_endpoint
from debugpilot.storage.config import Settings

MAX_FILE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024


class ComposeError(DebugPilotError):
    """A safe validation, availability or execution failure."""


@dataclass(frozen=True)
class ComposeProject:
    workspace: Path
    files: tuple[Path, ...]
    project_name: str
    fingerprints: tuple[str, ...]

    @classmethod
    def create(cls, workspace: Path, files: tuple[Path, ...], project_name: str):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project_name):
            raise ComposeError("Use a lowercase Compose project name with letters, digits, - or _.")
        if not 1 <= len(files) <= 16:
            raise ComposeError("Choose between 1 and 16 ordered Compose files.")
        try:
            workspace = Path(workspace).resolve(strict=True)
            if not workspace.is_dir():
                raise ComposeError("Choose an existing workspace directory.")
            resolved, fingerprints = [], []
            for file in files:
                file = Path(file)
                file = (workspace / file).resolve(strict=True)
                if not file.is_relative_to(workspace) or file.suffix.lower() not in {
                    ".yml",
                    ".yaml",
                }:
                    raise ComposeError("Compose YAML files must be inside the selected workspace.")
                with file.open("rb") as source:
                    data = source.read(MAX_FILE_BYTES + 1)
                if not data or len(data) > MAX_FILE_BYTES:
                    raise ComposeError("Compose files must be nonempty and at most 1 MiB each.")
                resolved.append(file)
                fingerprints.append(hashlib.sha256(data).hexdigest())
        except (OSError, ValueError) as error:
            raise ComposeError("Workspace or Compose files cannot be read.") from error
        return cls(workspace, tuple(resolved), project_name, tuple(fingerprints))


@dataclass(frozen=True)
class ComposePlan:
    project: ComposeProject
    action: str
    service: str | None
    executable: str
    endpoint: str

    def _arguments(self, config: str) -> tuple[str, ...]:
        arguments = [
            self.executable,
            "--host",
            self.endpoint,
            "--config",
            config,
            "compose",
            "--project-directory",
            str(self.project.workspace),
            "--project-name",
            self.project.project_name,
        ]
        for file in self.project.files:
            arguments.extend(("-f", str(file)))
        if self.action == "restart":
            arguments.append("restart")
        else:
            arguments.extend(("up", "-d", "--force-recreate", "--pull", "never"))
            if self.action == "rebuild":
                arguments.append("--build")
        if self.service is not None:
            arguments.extend(("--no-deps", self.service))
        return tuple(arguments)

    @property
    def display(self) -> str:
        """Display only; execution always uses an argument array, never this string."""
        return subprocess.list2cmdline(self._arguments("<private-config>"))


@dataclass(frozen=True)
class ComposeResult:
    exit_code: int
    output: str


class ComposeService:
    def __init__(self, settings: Settings, *, timeout_seconds: float = 600):
        # Revalidate even a caller-supplied model constructed without Pydantic validation.
        self.settings = Settings.model_validate(settings.model_dump())
        self.timeout_seconds = timeout_seconds
        self._executable = shutil.which("docker")

    def preview(self, project: ComposeProject, action: str, service: str | None = None):
        if not self._executable or Path(self._executable).suffix.lower() in {".cmd", ".bat"}:
            raise ComposeError(
                "Docker CLI executable is unavailable. Install Docker with Compose v2."
            )
        if action not in {"restart", "recreate", "rebuild"}:
            raise ComposeError("Choose restart, recreate or rebuild.")
        if service is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", service):
            raise ComposeError("Choose a valid Compose service name, not a container ID or option.")
        current = ComposeProject.create(project.workspace, project.files, project.project_name)
        if current != project:
            raise ComposeError("Compose files changed; review a new preview before confirming.")
        return ComposePlan(
            project,
            action,
            service,
            self._executable,
            self.settings.docker_endpoint or default_endpoint(),
        )

    async def run(self, plan: ComposePlan, *, confirmed: bool = False) -> ComposeResult:
        if confirmed is not True:
            raise ComposeError("Explicit confirmation is required before running Compose.")
        if self.preview(plan.project, plan.action, plan.service) != plan:
            raise ComposeError("Compose target changed; review a new preview before confirming.")
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 3600:
            raise ComposeError("Compose timeout must be between 0 and 3600 seconds.")
        process = None
        with tempfile.TemporaryDirectory(prefix="debugpilot-compose-") as directory:
            (Path(directory) / "config.json").write_text("{}", encoding="utf-8")
            environment = {
                key: value
                for key, value in os.environ.items()
                if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
            }
            environment.update(
                DOCKER_CONFIG=directory, COMPOSE_ANSI="never", COMPOSE_PROGRESS="plain"
            )
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    # Shield creation so a cancellation cannot lose a newly-created child handle.
                    launch = asyncio.create_task(
                        asyncio.create_subprocess_exec(
                            *plan._arguments(directory),
                            cwd=plan.project.workspace,
                            env=environment,
                            stdin=asyncio.subprocess.DEVNULL,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.STDOUT,
                            **({"creationflags": 0x08000000} if os.name == "nt" else {}),
                        )
                    )
                    try:
                        process = await asyncio.shield(launch)
                    except asyncio.CancelledError:
                        process, _ = await self._settle(launch)
                        raise
                    assert process.stdout is not None
                    retained = bytearray()
                    truncated = False
                    while chunk := await process.stdout.read(8192):
                        available = MAX_OUTPUT_BYTES - len(retained)
                        retained.extend(chunk[:available])
                        truncated |= len(chunk) > available
                    exit_code = await process.wait()
                    output = retained.decode("utf-8", errors="replace")
                    if truncated:
                        output += "\n[Compose output truncated; remaining output was drained.]\n"
                    return ComposeResult(exit_code, output)
            except TimeoutError as error:
                raise ComposeError(
                    "Compose timed out. Docker changes may remain; inspect the project."
                ) from error
            except OSError as error:
                raise ComposeError("Cannot start the local Docker CLI with Compose v2.") from error
            finally:
                if process is not None:
                    _, cancelled = await self._settle(asyncio.create_task(self._stop(process)))
                    if cancelled:
                        raise asyncio.CancelledError

    @staticmethod
    async def _settle(task):
        # Cleanup/creation must survive repeated caller cancellation until the handle is reaped.
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        return task.result(), cancelled

    @staticmethod
    async def _stop(process) -> None:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        # asyncio's process wait can hang on a full, paused stdout pipe even
        # after kill. Drain without retaining output so transport EOF can close.
        if process.stdout is not None:
            while await process.stdout.read(8192):
                pass
        await process.wait()
