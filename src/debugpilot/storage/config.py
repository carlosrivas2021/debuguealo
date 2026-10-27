import re
import tomllib
from pathlib import Path

from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from debugpilot.core.exceptions import ConfigurationError

MAX_CONFIG_BYTES = 64 * 1024


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    event_queue_size: int = Field(default=256, ge=1, le=10_000)
    docker_timeout_seconds: int = Field(default=3, ge=1, le=30)
    docker_endpoint: str | None = Field(default=None, max_length=4096)

    @field_validator("docker_endpoint")
    @classmethod
    def local_endpoint_only(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            value.startswith("unix:///")
            and not value.startswith("unix:////")
            and "\x00" not in value
        ):
            return value
        if re.fullmatch(r"npipe:////\./pipe/[A-Za-z0-9_-]+", value):
            return value
        raise ValueError("Only local Unix sockets and local Windows named pipes are supported.")


def config_path() -> Path:
    return user_config_path("debugpilot", appauthor=False) / "config.toml"


def load_settings(path: Path | None = None) -> Settings:
    target = path if path is not None else config_path()
    try:
        with target.open("rb") as stream:
            data = stream.read(MAX_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return Settings()
    except OSError:
        raise ConfigurationError("Cannot read configuration; check file permissions.") from None
    if len(data) > MAX_CONFIG_BYTES:
        raise ConfigurationError("Configuration exceeds the 64 KiB limit.")
    try:
        return Settings.model_validate(tomllib.loads(data.decode("utf-8")))
    except (UnicodeError, tomllib.TOMLDecodeError, ValidationError):
        raise ConfigurationError(
            "Invalid configuration. Check TOML syntax, supported keys, and value limits."
        ) from None
