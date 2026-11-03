"""Workspace-scoped launch profiles and safe Compose inventory discovery."""

from __future__ import annotations

import copy
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.docker.compose_overrides import validate_service_overrides
from debugpilot.storage.config import config_path

MAX_LAUNCH_BYTES = 256 * 1024
MAX_CONFIGURATIONS = 128
MAX_FILES = 16
MAX_PATH_LENGTH = 4096
PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
UP_FIELDS = {"build", "detach", "forceRecreate"}
MAX_SERVICES = 64
SERVICE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PROJECT_LABEL = "com.docker.compose.project"
WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"
CONFIG_FILES_LABEL = "com.docker.compose.project.config_files"
ENV_FILE_LABEL = "com.docker.compose.project.environment_file"


def default_workspace() -> Path:
    """Return the current directory as the explicitly opened workspace."""
    return Path.cwd().resolve(strict=True)


@dataclass(frozen=True)
class LaunchProfile:
    name: str | None
    project_name: str | None
    pending_reason: str | None
    raw: dict[str, Any] = field(repr=False)
    dynamic: bool = False


@dataclass(frozen=True)
class ResolvedLaunch:
    workspace: Path
    cwd: Path
    files: tuple[Path, ...]
    project_directory: Path
    project_name: str
    up: dict[str, bool] | None
    environment_files: tuple[Path, ...] = ()
    service_overrides: Any = field(default=None, repr=False)
    services: tuple[str, ...] = ()


def profile_services(raw: dict[str, Any]) -> tuple[str, ...] | None:
    """Return the optional explicit service subset, or None when it is invalid."""
    value = raw.get("services")
    if value is None or value == []:
        return ()
    if (
        not isinstance(value, list)
        or len(value) > MAX_SERVICES
        or any(not isinstance(name, str) or not SERVICE_NAME.fullmatch(name) for name in value)
        or len(set(value)) != len(value)
    ):
        return None
    return tuple(value)


def _is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _safe_workspace(value: Path) -> Path:
    try:
        path = Path(value).expanduser()
        if _is_reparse(path):
            raise ValueError
        resolved = path.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError
        return resolved
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ConfigurationError(
            "Launch profiles require an existing, non-symlink workspace."
        ) from error


class LaunchProfileStore:
    """Read, resolve and idempotently register profiles inside one workspace."""

    def __init__(self, workspace: Path | None = None):
        self.workspace = _safe_workspace(workspace) if workspace is not None else None
        self.path = (
            self.workspace / ".debugpilot" / "launch.json"
            if self.workspace is not None
            else config_path().parent / "launch.json"
        )
        self._discovered: list[dict[str, Any]] = []

    def _check_destination(self) -> None:
        parent = self.path.parent
        if _is_reparse(parent) or _is_reparse(self.path):
            raise ConfigurationError("Launch profile paths cannot be symlinks or reparse points.")
        try:
            if parent.exists() and not parent.is_dir():
                raise ConfigurationError("Launch profile directory is not a directory.")
        except OSError:
            raise ConfigurationError("Cannot inspect the launch profile directory.") from None

    def _read(self) -> tuple[dict[str, Any], bytes | None]:
        self._check_destination()
        try:
            with self.path.open("rb") as stream:
                data = stream.read(MAX_LAUNCH_BYTES + 1)
        except FileNotFoundError:
            return {"version": 1, "configurations": []}, None
        except OSError:
            raise ConfigurationError(
                "Cannot read launch profiles; check workspace permissions."
            ) from None
        if len(data) > MAX_LAUNCH_BYTES:
            raise ConfigurationError("Launch profile JSON exceeds the 256 KiB limit.")
        try:
            document = json.loads(data)
            if (
                not isinstance(document, dict)
                or type(document.get("version")) is not int
                or document["version"] != 1
            ):
                raise ValueError
            configurations = document.get("configurations")
            if not isinstance(configurations, list) or len(configurations) > MAX_CONFIGURATIONS:
                raise ValueError
            if any(not isinstance(item, dict) for item in configurations):
                raise ValueError
            return document, data
        except (ValueError, UnicodeError, RecursionError):
            raise ConfigurationError(
                "Invalid launch profile JSON; version 1 and configuration objects are required."
            ) from None

    def load(self) -> dict[str, Any]:
        """Return a detached document, preserving unknown root and profile fields."""
        document, _ = self._read()
        saved_projects = {
            item.get("projectName")
            for item in document["configurations"]
            if isinstance(item.get("projectName"), str)
        }
        document["configurations"].extend(
            copy.deepcopy(item)
            for item in self._discovered
            if item["projectName"] not in saved_projects
        )
        if len(document["configurations"]) > MAX_CONFIGURATIONS:
            raise ConfigurationError(
                f"Launch profiles support at most {MAX_CONFIGURATIONS} configurations."
            )
        return copy.deepcopy(document)

    def profiles(self, project_name: str | None = None) -> list[LaunchProfile]:
        document = self.load()
        saved, _ = self._read()
        saved_projects = [item.get("projectName") for item in saved["configurations"]]
        result = []
        for raw in document["configurations"]:
            project = raw.get("projectName")
            if project_name is not None and project != project_name:
                continue
            if "projectName" not in raw and raw.get("type") != "docker-compose":
                continue
            result.append(
                LaunchProfile(
                    name=raw.get("name") if isinstance(raw.get("name"), str) else None,
                    project_name=project if isinstance(project, str) else None,
                    pending_reason=self._pending_reason(raw),
                    raw=copy.deepcopy(raw),
                    dynamic=project not in saved_projects,
                )
            )
        return result

    def register(self, inventory: list[Any]) -> bool:
        """Refresh ephemeral detections; never write the user's launch file."""
        document, _ = self._read()
        saved_projects = {
            item.get("projectName")
            for item in document["configurations"]
            if isinstance(item.get("projectName"), str)
        }
        groups: dict[str, list[dict[str, Any]]] = {}
        for container in inventory:
            labels = getattr(container, "labels", None)
            if not isinstance(labels, dict):
                continue
            project = labels.get(PROJECT_LABEL)
            if (
                isinstance(project, str)
                and project.strip()
                and project.strip() not in saved_projects
            ):
                groups.setdefault(project.strip(), []).append(labels)
        if len(document["configurations"]) + len(groups) > MAX_CONFIGURATIONS:
            raise ConfigurationError(
                f"Launch profiles support at most {MAX_CONFIGURATIONS} configurations; "
                "no update was written."
            )
        discovered = []
        for project, members in sorted(groups.items()):
            metadata, pending = self._discovered_metadata(project, members)
            profile = {
                "name": f"Compose: {project}",
                "type": "docker-compose",
                "projectName": project,
                "source": "discovered",
                **metadata,
            }
            if pending:
                profile["pendingReason"] = pending
            discovered.append(profile)
        changed = discovered != [
            item for item in self._discovered if item["projectName"] not in saved_projects
        ]
        self._discovered = discovered
        return changed

    def save_configuration(self, configuration: dict[str, Any]) -> None:
        """Explicitly create a launch file; never replace an existing editor file."""
        profile = copy.deepcopy(configuration)
        profile["source"] = "manual"
        profile.pop("discoveryHash", None)
        profile.pop("pendingReason", None)
        self._create_launch({"version": 1, "configurations": [profile]})

    def ensure_launch_file(self) -> Path:
        """Create the starter launch file only when missing, then return its path."""
        self._check_destination()
        if self.path.exists():
            return self.path

        if self.workspace is None:
            self._create_launch({"version": 1, "configurations": []}, existing_ok=True)
            return self.path

        profile = None
        relative_example = Path("examples/multi-project/catalog/compose.yaml")
        example = self.workspace / relative_example
        try:
            resolved_example = example.resolve(strict=True)
            if resolved_example.is_relative_to(self.workspace) and resolved_example.is_file():
                profile = {
                    "name": "Catalog example",
                    "type": "docker-compose",
                    "projectName": "dp-demo-catalog",
                    "source": "manual",
                    "cwd": "${workspaceFolder}",
                    "files": [relative_example.as_posix()],
                    "up": {"build": True, "detach": True, "forceRecreate": True},
                }
        except (OSError, RuntimeError, ValueError):
            # Missing or unusable example assets never become fabricated launch paths.
            profile = None
        configurations = [profile] if profile is not None else []
        document = {"version": 1, "configurations": configurations}
        try:
            self._create_launch(document, existing_ok=True)
        except ConfigurationError:
            # If an editor won the create race, return its untouched file, even if
            # that document is malformed; opening it lets the user repair it.
            self._check_destination()
            if not self.path.exists():
                raise
        return self.path

    def resolve(self, profile: LaunchProfile) -> ResolvedLaunch | None:
        """Resolve only workspace-local inputs; never interprets shell variables."""
        raw = profile.raw
        project = raw.get("projectName")
        if (
            raw.get("type") != "docker-compose"
            or not isinstance(project, str)
            or not PROJECT_NAME.fullmatch(project)
        ):
            return None
        try:
            workspace = self.workspace
            if workspace is None:
                root_value = raw.get("workspaceFolder")
                if not isinstance(root_value, str) or not Path(root_value).is_absolute():
                    return None
                workspace = _safe_workspace(Path(root_value))
            cwd_value = raw.get("cwd")
            if not isinstance(cwd_value, str) or not cwd_value:
                return None
            cwd = self._resolve_path(cwd_value, workspace, workspace)
            if not cwd.is_dir():
                return None
            values = raw.get("files")
            if not isinstance(values, list) or not 1 <= len(values) <= MAX_FILES:
                return None
            files = tuple(self._resolve_path(item, cwd, workspace) for item in values)
            if any(not file.is_file() for file in files):
                return None
            directory_value = raw.get("projectDirectory")
            project_directory = (
                self._resolve_path(directory_value, cwd, workspace)
                if directory_value is not None
                else files[0].parent
            )
            if not project_directory.is_dir():
                return None
            up = raw.get("up")
            if up is not None:
                if not isinstance(up, dict) or set(up) - UP_FIELDS:
                    return None
                if any(type(value) is not bool for value in up.values()):
                    return None
                up = dict(up)
            environment_files = raw.get("environmentFiles", [])
            if not isinstance(environment_files, list) or len(environment_files) > MAX_FILES:
                return None
            env_paths = tuple(
                self._resolve_path(value, cwd, workspace) for value in environment_files
            )
            if any(not path.is_file() for path in env_paths):
                return None
            try:
                service_overrides = validate_service_overrides(raw.get("overrides"))
            except ValueError:
                return None
            if not service_overrides.services:
                service_overrides = None
            services = profile_services(raw)
            if services is None:
                return None
            return ResolvedLaunch(
                workspace=workspace,
                cwd=cwd,
                files=files,
                project_directory=project_directory,
                project_name=project,
                up=up,
                environment_files=env_paths,
                service_overrides=service_overrides,
                services=services,
            )
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError):
            return None

    def _resolve_path(self, value: Any, base: Path, workspace: Path | None = None) -> Path:
        workspace = workspace or self.workspace
        if workspace is None:
            raise ValueError
        if (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_PATH_LENGTH
            or "\x00" in value
        ):
            raise ValueError
        expanded = value.replace("${workspaceFolder}", str(workspace))
        if "$" in expanded or "{" in expanded or "}" in expanded:
            raise ValueError
        path = Path(expanded)
        if not path.is_absolute():
            path = base / path
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(workspace):
            raise ValueError
        return resolved

    def _discovered_metadata(
        self, project: str, members: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], str | None]:
        if self.workspace is None:
            return {}, "Central profiles require an explicitly saved project root."
        if not PROJECT_NAME.fullmatch(project):
            return {}, "Compose project name is not supported for launch profiles."
        observed = []
        for labels in members:
            working = labels.get(WORKING_DIR_LABEL)
            files = labels.get(CONFIG_FILES_LABEL)
            env = labels.get(ENV_FILE_LABEL)
            parsed_files = self._split_paths(files) if isinstance(files, str) else None
            parsed_env = self._split_paths(env) if isinstance(env, str) and env else []
            observed.append((working, parsed_files, parsed_env))
        if not observed or any(item != observed[0] for item in observed[1:]):
            return {}, "Compose services report conflicting directory or file labels."
        working, files, env = observed[0]
        if not isinstance(working, str) or not working or not files:
            return {}, "Compose working directory or configuration-file labels are missing."
        if env is None or len(files) > MAX_FILES or len(env) > MAX_FILES:
            return {}, "Compose metadata exceeds the supported file limit."
        try:
            cwd = self._map_local_path(working, self.workspace)
            if not cwd.is_dir():
                raise ValueError
            resolved_files = tuple(self._map_local_path(path, cwd) for path in files)
            if any(not path.is_file() for path in resolved_files):
                raise ValueError
            env_files = tuple(self._map_local_path(path, cwd) for path in env)
            if any(not path.is_file() for path in env_files):
                raise ValueError
            metadata = {
                "cwd": "${workspaceFolder}",
                "projectDirectory": self._workspace_expression(cwd),
                "files": [
                    self._relative_expression(path, self.workspace) for path in resolved_files
                ],
            }
            # Absence is meaningful: do not retain an old generated --env-file.
            metadata["environmentFiles"] = [
                self._relative_expression(path, self.workspace) for path in env_files
            ]
            return metadata, None
        except (OSError, RuntimeError, TypeError, ValueError):
            return {}, "Compose paths are stale, inaccessible, or outside the opened workspace."

    @staticmethod
    def _split_paths(value: str) -> list[str] | None:
        paths = [part.strip() for part in value.split(",")]
        if (
            not paths
            or len(paths) > MAX_FILES
            or any(not path or len(path) > MAX_PATH_LENGTH for path in paths)
        ):
            return None
        return paths

    def _map_local_path(self, value: str, base: Path) -> Path:
        if not value or len(value) > MAX_PATH_LENGTH or "\x00" in value:
            raise ValueError
        path = Path(value)
        if not path.is_absolute():
            path = base / path
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(self.workspace):
            raise ValueError
        return resolved

    def _workspace_expression(self, path: Path) -> str:
        relative = path.relative_to(self.workspace)
        return (
            "${workspaceFolder}"
            if not relative.parts
            else "${workspaceFolder}/" + relative.as_posix()
        )

    def _relative_expression(self, path: Path, base: Path) -> str:
        relative = os.path.relpath(path, base)
        return Path(relative).as_posix()

    def _pending_reason(self, raw: dict[str, Any]) -> str | None:
        if (
            raw.get("source") == "discovered"
            and isinstance(raw.get("pendingReason"), str)
            and raw["pendingReason"]
        ):
            return raw["pendingReason"]
        if raw.get("type") != "docker-compose":
            return "Profile type is missing or unsupported."
        if not raw.get("projectName"):
            return "Compose project name is missing."
        if not raw.get("cwd") or not raw.get("files"):
            return "Compose working directory or configuration files are missing."
        try:
            validate_service_overrides(raw.get("overrides"))
        except ValueError:
            return "Service overrides need attention."
        if profile_services(raw) is None:
            return "Profile services must be a list of unique Compose service names."
        try:
            if (
                self.resolve(LaunchProfile(None, raw.get("projectName"), None, copy.deepcopy(raw)))
                is None
            ):
                return "Compose paths or launch options need attention."
        except (OSError, ValueError):
            return "Compose paths or launch options need attention."
        return None

    def _create_launch(self, document: dict[str, Any], *, existing_ok: bool = False) -> bool:
        if len(document["configurations"]) > MAX_CONFIGURATIONS:
            raise ConfigurationError(
                f"Launch profiles support at most {MAX_CONFIGURATIONS} configurations."
            )
        temporary: Path | None = None
        try:
            self._check_destination()
            if self.path.exists():
                if existing_ok:
                    return False
                raise ConfigurationError(
                    "launch.json already exists; copy the configuration into your editor. "
                    "The file was not changed."
                )
            data = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            if len(data) > MAX_LAUNCH_BYTES:
                raise ValueError
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._check_destination()
            with tempfile.NamedTemporaryFile(
                dir=self.path.parent, suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._check_destination()
            # Linking publishes complete bytes atomically only if the name is absent.
            # Unlike replace, this cannot clobber a concurrent editor's new file.
            os.link(temporary, self.path)
            return True
        except ConfigurationError:
            raise
        except FileExistsError:
            if existing_ok:
                return False
            raise ConfigurationError(
                "launch.json was created by another editor; no update was written."
            ) from None
        except (OSError, ValueError, TypeError):
            raise ConfigurationError(
                "Cannot safely create launch profiles on this filesystem; "
                "no existing file was replaced."
            ) from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
