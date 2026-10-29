"""Bounded, versioned locations for explicitly configured local Compose projects."""

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.docker.compose import ComposeProject
from debugpilot.storage.config import config_path

MAX_PROJECT_BYTES = 256 * 1024


def projects_path() -> Path:
    return config_path().with_name("compose-projects.json")


class ProjectLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")
    workspace: str = Field(min_length=1, max_length=4096)
    files: list[str] = Field(min_length=1, max_length=16)

    @field_validator("workspace")
    @classmethod
    def absolute_workspace(cls, value: str) -> str:
        if not Path(value).is_absolute() or "\x00" in value:
            raise ValueError("An absolute workspace is required.")
        return value

    @field_validator("files")
    @classmethod
    def bounded_files(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 4096 or "\x00" in value for value in values):
            raise ValueError("Invalid Compose file paths.")
        return values

    def resolve(self) -> ComposeProject:
        return ComposeProject.create(Path(self.workspace), tuple(map(Path, self.files)), self.name)


class ProjectDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = Field(ge=1, le=1)
    projects: list[ProjectLocation] = Field(max_length=128)


class ComposeProjectStore:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else projects_path()

    def load(self) -> dict[str, ProjectLocation]:
        try:
            with self.path.open("rb") as stream:
                data = stream.read(MAX_PROJECT_BYTES + 1)
        except FileNotFoundError:
            return {}
        except OSError:
            raise ConfigurationError(
                "Cannot read Compose project JSON; check permissions."
            ) from None
        try:
            if len(data) > MAX_PROJECT_BYTES:
                raise ValueError
            document = ProjectDocument.model_validate(json.loads(data))
            projects = {project.name: project for project in document.projects}
            if len(projects) != len(document.projects):
                raise ValueError
            return projects
        except (ValueError, UnicodeError, ValidationError, RecursionError):
            raise ConfigurationError(
                "Invalid Compose project JSON; check version 1, project paths and size limits."
            ) from None

    def save(self, project: ComposeProject) -> None:
        projects = self.load()
        projects[project.project_name] = ProjectLocation(
            name=project.project_name,
            workspace=str(project.workspace),
            files=list(map(str, project.files)),
        )
        temporary = None
        try:
            document = ProjectDocument(version=1, projects=list(projects.values()))
            data = (document.model_dump_json(indent=2) + "\n").encode("utf-8")
            if len(data) > MAX_PROJECT_BYTES:
                raise ValueError
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.path.parent, suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except (OSError, ValueError):
            raise ConfigurationError(
                "Cannot save Compose project JSON; existing configuration was preserved."
            ) from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
