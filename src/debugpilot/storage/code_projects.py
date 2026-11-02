"""Dedicated central code profiles; loading never writes or executes commands."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.config import config_path


@dataclass(frozen=True)
class CodeProject:
    name: str
    root: Path
    command: tuple[str, ...]


class CodeProjectStore:
    def __init__(self):
        self.path = config_path().parent / "projects" / "launch.json"

    def ensure_launch_file(self) -> Path:
        """Publish an empty starter only on explicit request; never replace a file."""
        if self.path.exists():
            return self.path
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(b'{"version": 1, "configurations": []}\n')
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                pass  # A concurrent editor owns the file; keep it untouched.
            return self.path
        except OSError:
            raise ConfigurationError("Cannot create code launch.json; check permissions.") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def profiles(self) -> list[CodeProject]:
        try:
            with self.path.open("rb") as stream:
                data = stream.read(256 * 1024 + 1)
        except FileNotFoundError:
            return []
        except OSError:
            raise ConfigurationError("Cannot read code launch.json; check permissions.") from None
        try:
            if len(data) > 256 * 1024:
                raise ValueError
            document = json.loads(data)
            if not isinstance(document, dict) or type(document.get("version")) is not int:
                raise ValueError
            entries = document.get("configurations")
            if document["version"] != 1 or not isinstance(entries, list) or len(entries) > 128:
                raise ValueError
            profiles = []
            names = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError
                name = entry.get("name")
                folder = entry.get("workspaceFolder")
                command = entry.get("command")
                if not self._text(name) or name in names or not self._text(folder):
                    raise ValueError
                root = Path(folder)
                if not root.is_absolute() or not root.is_dir():
                    raise ValueError
                if not isinstance(command, list) or not command or len(command) > 128:
                    raise ValueError
                if any(not self._text(arg) for arg in command):
                    raise ValueError
                profiles.append(CodeProject(name, root.resolve(strict=True), tuple(command)))
                names.add(name)
            return profiles
        except (ValueError, TypeError, UnicodeError, OSError, RuntimeError, RecursionError):
            raise ConfigurationError(
                "Invalid code launch.json: use version 1 and up to 128 configurations with "
                "unique names, existing absolute workspaceFolder directories and nonempty "
                "command argument arrays."
            ) from None

    @staticmethod
    def _text(value: object) -> bool:
        return (
            isinstance(value, str)
            and bool(value.strip())
            and len(value) <= 4096
            and "\x00" not in value
        )
