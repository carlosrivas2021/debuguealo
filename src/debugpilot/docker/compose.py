"""Explicit, confirmation-gated local Compose operations without a shell."""

import asyncio
import codecs
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from debugpilot.core.exceptions import DebugPilotError
from debugpilot.docker.compose_overrides import (
    _ValidatedServiceOverrides,
    apply_service_overrides,
    validate_service_overrides,
)
from debugpilot.docker.diagnostics import default_endpoint
from debugpilot.storage.config import Settings

MAX_FILE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
COMPOSE_ENVIRONMENT_KEYS = frozenset(
    {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PROGRAMFILES", "PROGRAMDATA"}
)
_ENV_FILE_KEY = re.compile(r"\benv_file\s*:")
MAX_CALLBACK_LINE_CHARS = 16_384
MAX_RETRY_ENV_FILES = 64


class ComposeError(DebugPilotError):
    """A safe validation, availability or execution failure."""


@dataclass(frozen=True)
class ComposeUpOptions:
    """The supported, non-shell Compose `up` options for a launch profile."""

    build: bool = False
    detach: bool = True
    force_recreate: bool = False

    def __post_init__(self):
        if any(type(value) is not bool for value in (self.build, self.detach, self.force_recreate)):
            raise ValueError("Compose up options must be boolean values.")


@dataclass(frozen=True)
class ComposeProject:
    workspace: Path
    files: tuple[Path, ...]
    project_name: str
    fingerprints: tuple[str, ...]
    project_directory: Path | None = None
    up: ComposeUpOptions | None = None
    process_cwd: Path | None = None
    environment_files: tuple[Path, ...] = ()
    environment_fingerprints: tuple[str, ...] = ()
    service_overrides: _ValidatedServiceOverrides | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        workspace: Path,
        files: tuple[Path, ...],
        project_name: str,
        *,
        project_directory: Path | None = None,
        up: ComposeUpOptions | None = None,
        process_cwd: Path | None = None,
        environment_files: tuple[Path, ...] = (),
        service_overrides=None,
    ):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project_name):
            raise ComposeError("Use a lowercase Compose project name with letters, digits, - or _.")
        if not 1 <= len(files) <= 16:
            raise ComposeError("Choose between 1 and 16 ordered Compose files.")
        try:
            workspace = Path(workspace).resolve(strict=True)
            if not workspace.is_dir():
                raise ComposeError("Choose an existing workspace directory.")
            if project_directory is not None:
                project_directory = Path(project_directory)
                if not project_directory.is_absolute():
                    project_directory = workspace / project_directory
                project_directory = project_directory.resolve(strict=True)
                if (
                    not project_directory.is_relative_to(workspace)
                    or not project_directory.is_dir()
                ):
                    raise ComposeError(
                        "Compose project directory must be inside the selected workspace."
                    )
            if up is not None and not isinstance(up, ComposeUpOptions):
                raise ComposeError("Compose up options must use ComposeUpOptions.")
            if service_overrides is not None:
                try:
                    service_overrides = validate_service_overrides(service_overrides)
                except ValueError as error:
                    raise ComposeError("Invalid service overrides.") from error
                if not service_overrides.services:
                    service_overrides = None
            if process_cwd is not None:
                process_cwd = (workspace / Path(process_cwd)).resolve(strict=True)
                if not process_cwd.is_relative_to(workspace) or not process_cwd.is_dir():
                    raise ComposeError("Compose process directory must be inside the workspace.")
            if len(environment_files) > 16:
                raise ComposeError("Choose at most 16 environment files.")
            env_paths, env_fingerprints = [], []
            for value in environment_files:
                path = (workspace / Path(value)).resolve(strict=True)
                if not path.is_relative_to(workspace) or not path.is_file():
                    raise ComposeError("Environment files must be inside the workspace.")
                with path.open("rb") as source:
                    data = source.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    raise ComposeError("Environment files must be at most 1 MiB each.")
                env_paths.append(path)
                env_fingerprints.append(hashlib.sha256(data).hexdigest())
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
        except (OSError, TypeError, ValueError) as error:
            raise ComposeError("Workspace or Compose files cannot be read.") from error
        return cls(
            workspace,
            tuple(resolved),
            project_name,
            tuple(fingerprints),
            project_directory,
            up,
            process_cwd,
            tuple(env_paths),
            tuple(env_fingerprints),
            service_overrides,
        )


@dataclass(frozen=True)
class ComposePlan:
    project: ComposeProject
    action: str
    service: str | None
    executable: str
    endpoint: str

    def _arguments(self, config: str, *, pull_missing: bool = False) -> tuple[str, ...]:
        arguments = [
            self.executable,
            "--host",
            self.endpoint,
            "--config",
            config,
            "compose",
            "--project-directory",
            str(self.project.project_directory or self.project.workspace),
            "--project-name",
            self.project.project_name,
        ]
        for file in self.project.environment_files:
            arguments.extend(("--env-file", str(file)))
        for file in self.project.files:
            arguments.extend(("-f", str(file)))
        if self.action == "restart":
            arguments.append("restart")
        else:
            arguments.append("up")
            configured_up = self.project.up if self.action == "start" else None
            if configured_up is None or configured_up.detach:
                arguments.append("-d")
            if self.action != "start" or (configured_up and configured_up.force_recreate):
                arguments.append("--force-recreate")
            arguments.extend(("--pull", "missing" if pull_missing else "never"))
            if self.action == "rebuild" or (configured_up and configured_up.build):
                arguments.append("--build")
        if self.service is not None:
            arguments.extend(("--no-deps", self.service))
        return tuple(arguments)

    @property
    def display(self) -> str:
        """Display safe arguments only; execution always uses an argument array."""
        if self.project.service_overrides is not None:
            arguments = _effective_arguments(self, "<private-config>", pull_missing=False)
        else:
            arguments = self._arguments("<private-config>")
        return subprocess.list2cmdline(arguments)


@dataclass(frozen=True)
class ComposeResult:
    exit_code: int
    output: str


@dataclass(frozen=True, repr=False)
class _RuntimeSnapshot:
    plan: ComposePlan
    semantic_json: str = field(repr=False)
    fingerprint: str
    direct_inputs: tuple[tuple[str, str], ...]
    environment: tuple[tuple[str, str], ...]

    def __repr__(self):
        return "<ComposeRuntimeSnapshot>"


def _escaped_interpolation_values(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [_escaped_interpolation_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _escaped_interpolation_values(item) for key, item in value.items()}
    return value


def _effective_arguments(plan: ComposePlan, config: str, *, pull_missing: bool) -> tuple[str, ...]:
    arguments = list(plan._arguments(config, pull_missing=pull_missing))
    compose_index = arguments.index("compose")
    index = compose_index + 1
    first_file = None
    while index < len(arguments):
        if arguments[index] in {"--project-directory", "--project-name", "--env-file"}:
            index += 2
        elif arguments[index] == "-f":
            if first_file is None:
                first_file = index
            del arguments[index : index + 2]
        else:
            break
    if first_file is None:
        raise ComposeError("Cannot build effective Compose arguments.")
    arguments[first_file:first_file] = ("-f", str(Path(config) / "effective-compose.json"))
    return tuple(arguments)


def _env_file_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    if not value or any(char in value for char in ("$", "{", "}", "\x00", "#")):
        raise ValueError("Unsupported env_file path syntax")
    return value


def _env_file_paths(source: str, base: Path) -> tuple[Path, ...]:
    """Read only unambiguous scalar env_file paths; unsupported YAML fails closed."""
    lines = source.splitlines()
    paths = []
    for match in _ENV_FILE_KEY.finditer(source):
        line_number = source.count("\n", 0, match.start())
        line = lines[line_number]
        indent = len(line) - len(line.lstrip())
        value = source[match.end() :].lstrip(" \t")
        values = []
        if value.startswith("["):
            end = value.find("]")
            if end < 0:
                raise ValueError("Unterminated env_file list")
            body = value[1:end].strip()
            values = [] if not body else [_env_file_value(item) for item in body.split(",")]
        elif value and value[0] not in "\r\n":
            token = re.split(r"[,\]}#\r\n]", value, maxsplit=1)[0].strip()
            if token.lower() not in {"null", "~"}:
                values = [_env_file_value(token)]
        else:
            for following in lines[line_number + 1 :]:
                if not following.strip() or following.lstrip().startswith("#"):
                    continue
                following_indent = len(following) - len(following.lstrip())
                if following_indent <= indent:
                    break
                child = following.lstrip()
                if not child.startswith("-"):
                    raise ValueError("Unsupported env_file list syntax")
                values.append(_env_file_value(child[1:]))
        paths.extend(base / item for item in values)
    return tuple(paths)


def _fingerprint_runtime_file(path: Path, workspace: Path) -> tuple[Path, str]:
    try:
        path.lstat()
    except FileNotFoundError:
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(workspace):
            raise ComposeError(
                "Runtime environment files must remain inside the workspace."
            ) from None
        return resolved, "missing"
    except OSError as error:
        raise ComposeError("Cannot verify a Compose runtime environment file.") from error
    try:
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ComposeError("Runtime environment files cannot be symlinks or junctions.")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(workspace) or not resolved.is_file():
            raise ComposeError("Runtime environment files must be workspace-local files.")
        with resolved.open("rb") as source:
            data = source.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ComposeError("Runtime environment files must be at most 1 MiB.")
    except ComposeError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ComposeError("Cannot verify a Compose runtime environment file.") from error
    return resolved, hashlib.sha256(data).hexdigest()


def _fingerprint_resolved_env_file(path: Path) -> tuple[str, str]:
    """Hash only an env_file path returned by the bounded Compose config probe."""
    try:
        path.lstat()
    except FileNotFoundError:
        resolved = path.resolve(strict=False)
        return resolved.as_posix(), "missing"
    except OSError as error:
        raise ComposeError("Cannot verify a resolved Compose env_file.") from error
    try:
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ComposeError("Resolved Compose env_files cannot be symlinks or junctions.")
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ComposeError("Resolved Compose env_files must be files.")
        with resolved.open("rb") as source:
            data = source.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ComposeError("Resolved Compose env_files must be at most 1 MiB.")
    except ComposeError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ComposeError("Cannot verify a resolved Compose env_file.") from error
    return resolved.as_posix(), hashlib.sha256(data).hexdigest()


def _compose_config_arguments(plan: ComposePlan, config: str) -> tuple[str, ...]:
    arguments = list(plan._arguments(config))
    compose_index = arguments.index("compose")
    command_index = compose_index + 1
    while command_index < len(arguments):
        if arguments[command_index] in {
            "--project-directory",
            "--project-name",
            "--env-file",
            "-f",
        }:
            command_index += 2
            continue
        if arguments[command_index] in {"up", "restart"}:
            break
        command_index += 1
    if command_index >= len(arguments):
        raise ComposeError("Cannot build a read-only Compose config probe.")
    del arguments[command_index:]
    arguments.extend(("config", "--format", "json"))
    return tuple(arguments)


def _resolved_env_file_paths(config: dict, project: ComposeProject) -> tuple[Path, ...]:
    services = config.get("services", {})
    if not isinstance(services, dict):
        raise ValueError("Unsupported resolved services shape")
    paths: set[Path] = set()
    base = project.project_directory or project.workspace
    for service in services.values():
        if not isinstance(service, dict):
            raise ValueError("Unsupported resolved service shape")
        declarations = service.get("env_file", ())
        if declarations is None:
            continue
        if isinstance(declarations, (str, dict)):
            declarations = (declarations,)
        if not isinstance(declarations, (list, tuple)):
            raise ValueError("Unsupported resolved env_file shape")
        for declaration in declarations:
            value = (
                declaration
                if isinstance(declaration, str)
                else declaration.get("path")
                if isinstance(declaration, dict)
                else None
            )
            if not isinstance(value, str) or not value:
                raise ValueError("Unsupported resolved env_file path")
            path = Path(value)
            if not path.is_absolute():
                path = base / path
            paths.add(path)
            if len(paths) > MAX_RETRY_ENV_FILES:
                raise ValueError("Too many resolved env_files")
    return tuple(sorted(paths, key=lambda path: path.as_posix()))


class ComposeService:
    def __init__(self, settings: Settings, *, timeout_seconds: float = 600):
        # Revalidate even a caller-supplied model constructed without Pydantic validation.
        self.settings = Settings.model_validate(settings.model_dump())
        self.timeout_seconds = timeout_seconds
        self._executable = shutil.which("docker")
        self._retry_snapshot: _RuntimeSnapshot | None = None

    def preview(self, project: ComposeProject, action: str, service: str | None = None):
        if not self._executable or Path(self._executable).suffix.lower() in {".cmd", ".bat"}:
            raise ComposeError(
                "Docker CLI executable is unavailable. Install Docker with Compose v2."
            )
        if action not in {"start", "restart", "recreate", "rebuild"}:
            raise ComposeError("Choose start, restart, recreate or rebuild.")
        if service is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", service):
            raise ComposeError("Choose a valid Compose service name, not a container ID or option.")
        current = ComposeProject.create(
            project.workspace,
            project.files,
            project.project_name,
            project_directory=project.project_directory,
            up=project.up,
            process_cwd=project.process_cwd,
            environment_files=project.environment_files,
            service_overrides=project.service_overrides,
        )
        if current != project:
            raise ComposeError("Compose files changed; review a new preview before confirming.")
        return ComposePlan(
            project,
            action,
            service,
            self._executable,
            self.settings.docker_endpoint or default_endpoint(),
        )

    async def capture_retry_environment(self, plan: ComposePlan) -> str:
        """Hash the pinned plan and bounded effective Compose runtime configuration."""
        if plan.project.service_overrides is not None:
            snapshot = await self._resolve_override_snapshot(plan)
            self._retry_snapshot = snapshot
            return snapshot.fingerprint
        if self.preview(plan.project, plan.action, plan.service) != plan:
            raise ComposeError("Compose target changed; review a new preview before confirming.")
        try:
            direct_before = self._direct_retry_inputs(plan)
            result = await self._run_process(
                plan.project, lambda config: _compose_config_arguments(plan, config)
            )
            if result.exit_code != 0 or len(result.output.encode("utf-8")) > MAX_OUTPUT_BYTES:
                raise ValueError("Compose config probe failed or was truncated")
            resolved_config = json.loads(result.output)
            if not isinstance(resolved_config, dict):
                raise ValueError("Compose config did not return a JSON object")
            canonical_config = json.dumps(
                resolved_config, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            resolved_env_files = tuple(
                _fingerprint_resolved_env_file(path)
                for path in _resolved_env_file_paths(resolved_config, plan.project)
            )
            direct_after = self._direct_retry_inputs(plan)
            if direct_before != direct_after:
                raise ComposeError("Compose runtime environment changed during consent snapshot.")
            if self.preview(plan.project, plan.action, plan.service) != plan:
                raise ComposeError("Compose target changed during consent snapshot.")
        except ComposeError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ComposeError(
                "Cannot resolve the Compose runtime environment for download consent."
            ) from error

        execution_environment = sorted(
            (key, value)
            for key, value in os.environ.items()
            if key.upper() in COMPOSE_ENVIRONMENT_KEYS
        )
        material = json.dumps(
            {
                "plan": plan._arguments("<private-config>"),
                "resolved_config": canonical_config,
                "resolved_env_files": resolved_env_files,
                "direct_inputs": direct_before,
                "environment": execution_environment,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    async def _resolve_override_snapshot(self, plan: ComposePlan) -> _RuntimeSnapshot:
        if self.preview(plan.project, plan.action, plan.service) != plan:
            raise ComposeError("Compose target changed; review a new preview before confirming.")
        try:
            direct_before = self._direct_retry_inputs(plan)
            result = await self._run_process(
                plan.project, lambda config: _compose_config_arguments(plan, config)
            )
            if result.exit_code != 0 or len(result.output.encode("utf-8")) > MAX_OUTPUT_BYTES:
                raise ValueError
            model = json.loads(result.output)
            if not isinstance(model, dict):
                raise ValueError
            effective = apply_service_overrides(model, plan.project.service_overrides)
            direct_after = self._direct_retry_inputs(plan)
            if direct_before != direct_after:
                raise ComposeError("Compose runtime environment changed during consent snapshot.")
            if self.preview(plan.project, plan.action, plan.service) != plan:
                raise ComposeError("Compose target changed during consent snapshot.")
        except ComposeError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ComposeError("Cannot resolve or apply Compose service overrides.") from error

        semantic_json = json.dumps(
            effective, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        environment = tuple(
            sorted(
                (key, value)
                for key, value in os.environ.items()
                if key.upper() in COMPOSE_ENVIRONMENT_KEYS
            )
        )
        direct_inputs = tuple(direct_before)
        material = json.dumps(
            {
                "plan": plan._arguments("<private-config>"),
                "model": semantic_json,
                "direct_inputs": direct_inputs,
                "environment": environment,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return _RuntimeSnapshot(
            plan,
            semantic_json,
            hashlib.sha256(material).hexdigest(),
            direct_inputs,
            environment,
        )

    def _approved_override_snapshot(self, plan: ComposePlan, fingerprint: str):
        snapshot = self._retry_snapshot
        if snapshot is None or snapshot.plan != plan or snapshot.fingerprint != fingerprint:
            raise ComposeError("Compose runtime environment changed; download retry cancelled.")
        if self.preview(plan.project, plan.action, plan.service) != plan:
            raise ComposeError("Compose target changed; review a new preview before confirming.")
        direct = tuple(self._direct_retry_inputs(plan))
        environment = tuple(
            sorted(
                (key, value)
                for key, value in os.environ.items()
                if key.upper() in COMPOSE_ENVIRONMENT_KEYS
            )
        )
        if direct != snapshot.direct_inputs or environment != snapshot.environment:
            raise ComposeError("Compose runtime environment changed; download retry cancelled.")
        return snapshot

    @staticmethod
    def _direct_retry_inputs(plan: ComposePlan) -> tuple[tuple[str, str], ...]:
        project = plan.project
        workspace = project.workspace
        inputs: set[Path] = set(project.environment_files)
        inputs.update(
            directory / ".env"
            for directory in {
                project.process_cwd or workspace,
                project.project_directory or workspace,
            }
        )
        for file in project.files:
            try:
                with file.open("rb") as source_file:
                    source = source_file.read(MAX_FILE_BYTES + 1)
                if len(source) > MAX_FILE_BYTES:
                    raise ValueError("Compose file exceeds the preview size bound")
                inputs.update(_env_file_paths(source.decode("utf-8"), file.parent))
            except (OSError, UnicodeError, ValueError) as error:
                raise ComposeError(
                    "Cannot verify the Compose runtime environment for download consent."
                ) from error
        if len(inputs) > MAX_RETRY_ENV_FILES:
            raise ComposeError("Too many direct Compose runtime environment files to verify.")
        observed = []
        for path in sorted(inputs, key=lambda value: str(value)):
            resolved, content_hash = _fingerprint_runtime_file(path, workspace)
            observed.append((resolved.relative_to(workspace).as_posix(), content_hash))
        return tuple(observed)

    async def run(
        self,
        plan: ComposePlan,
        *,
        confirmed: bool = False,
        pull_missing: bool = False,
        retry_fingerprint: str | None = None,
        on_output: Callable[[str], None] | None = None,
        retry_preflight: Callable[[], bool] | None = None,
    ) -> ComposeResult:
        """Run a confirmed Compose action.

        Restart only affects existing containers; use recreate to apply changed
        environment or published-port overrides.
        """
        if confirmed is not True:
            raise ComposeError("Explicit confirmation is required before running Compose.")
        if type(pull_missing) is not bool:
            raise ComposeError("Missing-image permission must be a boolean value.")
        if on_output is not None and not callable(on_output):
            raise ComposeError("Compose output callback must be callable.")
        if retry_preflight is not None and not callable(retry_preflight):
            raise ComposeError("Retry preflight must be callable.")
        if pull_missing and plan.action == "restart":
            raise ComposeError("Missing-image retry is available only for Compose up actions.")
        snapshot = None
        if pull_missing:
            if not isinstance(retry_fingerprint, str) or not re.fullmatch(
                r"[0-9a-f]{64}", retry_fingerprint
            ):
                raise ComposeError("A current runtime fingerprint is required for download retry.")
            if retry_preflight is not None and not retry_preflight():
                raise ComposeError("Launch profile changed; download retry cancelled.")
            if plan.project.service_overrides is not None:
                snapshot = self._approved_override_snapshot(plan, retry_fingerprint)
            elif await self.capture_retry_environment(plan) != retry_fingerprint:
                raise ComposeError("Compose runtime environment changed; download retry cancelled.")
            if retry_preflight is not None and not retry_preflight():
                raise ComposeError("Launch profile changed; download retry cancelled.")
        elif plan.project.service_overrides is not None:
            snapshot = await self._resolve_override_snapshot(plan)
        elif self.preview(plan.project, plan.action, plan.service) != plan:
            raise ComposeError("Compose target changed; review a new preview before confirming.")

        if snapshot is None:
            arguments = (
                (lambda config: plan._arguments(config, pull_missing=True))
                if pull_missing
                else plan._arguments
            )
            return await self._run_process(plan.project, arguments, on_output=on_output)

        def arguments(config):
            return _effective_arguments(plan, config, pull_missing=pull_missing)
        if pull_missing:
            self._retry_snapshot = None
        return await self._run_process(
            plan.project,
            arguments,
            on_output=on_output,
            effective_json=snapshot.semantic_json,
        )

    async def inspect_project(
        self,
        workspace: Path,
        files: tuple[Path, ...],
        *,
        project_directory: Path | None = None,
        up: ComposeUpOptions | None = None,
        process_cwd: Path | None = None,
        environment_files: tuple[Path, ...] = (),
    ) -> ComposeProject:
        """Resolve Compose's own name without overriding it or exposing configuration."""
        project = ComposeProject.create(
            workspace,
            files,
            "inspection",
            project_directory=project_directory,
            up=up,
            process_cwd=process_cwd,
            environment_files=environment_files,
        )
        # Reuse availability/endpoint checks without executing a mutating operation.
        plan = self.preview(project, "start")

        def arguments(config):
            args = list(plan._arguments(config))
            index = args.index("--project-name")
            del args[index : index + 2]
            del args[args.index("up") :]
            return (*args, "config", "--format", "json")

        result = await self._run_process(project, arguments)
        try:
            if result.exit_code or len(result.output.encode()) > MAX_OUTPUT_BYTES:
                raise ValueError
            name = json.loads(result.output)["name"]
            if not isinstance(name, str):
                raise ValueError
            resolved = ComposeProject.create(
                workspace,
                files,
                name,
                project_directory=project.project_directory,
                up=project.up,
                process_cwd=project.process_cwd,
                environment_files=project.environment_files,
            )
            if resolved.fingerprints != project.fingerprints:
                raise ValueError
            return resolved
        except (ValueError, KeyError, TypeError, ComposeError) as error:
            raise ComposeError(
                "Cannot inspect Compose configuration. Check trusted YAML, interpolation and CLI."
            ) from error

    async def _run_process(
        self,
        project: ComposeProject,
        arguments,
        *,
        on_output: Callable[[str], None] | None = None,
        effective_json: str | None = None,
    ) -> ComposeResult:
        """One isolated, bounded, cancellation-safe subprocess path for config and execution."""
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 3600:
            raise ComposeError("Compose timeout must be between 0 and 3600 seconds.")
        process = None
        with tempfile.TemporaryDirectory(prefix="debugpilot-compose-") as directory:
            (Path(directory) / "config.json").write_text("{}", encoding="utf-8")
            if effective_json is not None:
                effective_path = Path(directory) / "effective-compose.json"
                try:
                    descriptor = os.open(
                        effective_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                    )
                    with os.fdopen(descriptor, "w", encoding="utf-8") as private_file:
                        model = json.loads(effective_json)
                        private_file.write(
                            json.dumps(
                                _escaped_interpolation_values(model),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        )
                        private_file.flush()
                except OSError:
                    raise ComposeError("Cannot prepare private Compose configuration.") from None
            environment = {
                key: value
                for key, value in os.environ.items()
                if key.upper() in COMPOSE_ENVIRONMENT_KEYS
            }
            environment.update(
                DOCKER_CONFIG=directory, COMPOSE_ANSI="never", COMPOSE_PROGRESS="plain"
            )
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    # Shield creation so a cancellation cannot lose a newly-created child handle.
                    launch = asyncio.create_task(
                        asyncio.create_subprocess_exec(
                            sys.executable,
                            str(Path(__file__).with_name("_compose_worker.py")),
                            *arguments(directory),
                            cwd=project.process_cwd or project.workspace,
                            env=environment,
                            stdin=asyncio.subprocess.DEVNULL,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.STDOUT,
                            **({"creationflags": 0x08000000} if os.name == "nt" else {}),
                            **({"start_new_session": True} if os.name != "nt" else {}),
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
                    decoder = codecs.getincrementaldecoder("utf-8")("replace")
                    callback_buffer = ""
                    stream_callback = on_output

                    def emit_complete_lines(text: str, *, final: bool = False) -> None:
                        nonlocal callback_buffer, stream_callback
                        if stream_callback is None:
                            return
                        callback_buffer += text
                        while callback_buffer:
                            delimiters = [
                                position
                                for position in (
                                    callback_buffer.find("\n"),
                                    callback_buffer.find("\r"),
                                )
                                if position >= 0
                            ]
                            if delimiters:
                                position = min(delimiters)
                                line = callback_buffer[:position]
                                consumed = (
                                    2
                                    if (
                                        callback_buffer[position] == "\r"
                                        and callback_buffer[position : position + 2] == "\r\n"
                                    )
                                    else 1
                                )
                                callback_buffer = callback_buffer[position + consumed :]
                            elif len(callback_buffer) > MAX_CALLBACK_LINE_CHARS:
                                line = callback_buffer[:MAX_CALLBACK_LINE_CHARS]
                                callback_buffer = callback_buffer[MAX_CALLBACK_LINE_CHARS:]
                            elif final:
                                line, callback_buffer = callback_buffer, ""
                            else:
                                break
                            try:
                                if line:
                                    stream_callback(line)
                            except Exception:
                                # UI logging must not interrupt draining/reaping the process.
                                stream_callback = None
                                callback_buffer = ""
                                return

                    while chunk := await process.stdout.read(8192):
                        available = MAX_OUTPUT_BYTES - len(retained)
                        retained.extend(chunk[:available])
                        truncated |= len(chunk) > available
                        if stream_callback is not None:
                            emit_complete_lines(decoder.decode(chunk))
                    if stream_callback is not None:
                        emit_complete_lines(decoder.decode(b"", final=True), final=True)
                    exit_code = await process.wait()
                    output = retained.decode("utf-8", errors="replace")
                    if truncated:
                        marker = "\n[Compose output truncated; remaining output was drained.]\n"
                        output += marker
                        if stream_callback is not None:
                            emit_complete_lines(marker, final=True)
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
        if os.name != "nt" and getattr(process, "pid", None) is not None:
            # The helper starts a fresh session. Its entire group is ours,
            # including plugin descendants after the direct helper has exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                # A wrapped or test child may not own a process group; still
                # terminate the direct child so pipe draining cannot wait forever.
                if process.returncode is None:
                    process.kill()
        elif process.returncode is None:
            try:
                process.kill()  # Windows helper owns a kill-on-close Job Object.
            except ProcessLookupError:
                pass
        # Drain without retaining output so transport EOF can close after kill.
        if process.stdout is not None:
            while await process.stdout.read(8192):
                pass
        await process.wait()
