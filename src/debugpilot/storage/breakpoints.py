"""Persistent requested Code breakpoint intent, separate from launch profiles."""

import json
import os
import tempfile
from pathlib import Path

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.config import config_path

MAX_BREAKPOINT_BYTES = 256 * 1024
MAX_BREAKPOINT_FILES = 4096
MAX_LINES_PER_FILE = 100_000


class BreakpointStore:
    """Store requested line marks centrally; debugger verification is never persisted."""

    def __init__(self, path: Path | None = None):
        self.path = (
            path if path is not None
            else config_path().parent / "projects" / "breakpoints.json"
        )

    def load(self) -> dict[tuple[Path, Path], tuple[int, ...]]:
        try:
            with self.path.open("rb") as stream:
                data = stream.read(MAX_BREAKPOINT_BYTES + 1)
        except FileNotFoundError:
            return {}
        except OSError:
            raise ConfigurationError(
                "Cannot read Code breakpoints; check the projects directory permissions."
            ) from None
        try:
            if len(data) > MAX_BREAKPOINT_BYTES:
                raise ValueError
            document = json.loads(data)
            if (not isinstance(document, dict) or type(document.get("version")) is not int
                    or document["version"] != 1):
                raise ValueError
            entries = document.get("breakpoints")
            if not isinstance(entries, list) or len(entries) > MAX_BREAKPOINT_FILES:
                raise ValueError
            marks = {}
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {"root", "file", "lines"}:
                    raise ValueError
                if not isinstance(entry["root"], str) or not isinstance(entry["file"], str):
                    raise ValueError
                root = self._canonical_path(entry["root"])
                path = self._canonical_path(entry["file"])
                if not path.is_relative_to(root):
                    raise ValueError
                lines = entry["lines"]
                if (not isinstance(lines, list) or not lines or len(lines) > MAX_LINES_PER_FILE
                        or any(type(line) is not int or line <= 0 for line in lines)
                        or lines != sorted(set(lines))):
                    raise ValueError
                key = (root, path)
                if key in marks:
                    raise ValueError
                marks[key] = tuple(lines)
            return marks
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OSError,
                RuntimeError):
            raise ConfigurationError(
                "Invalid Code breakpoints; repair projects/breakpoints.json. "
                "The existing file was not changed."
            ) from None

    def save(self, marks: dict[tuple[Path, Path], set[int]]) -> None:
        # Refuse to replace invalid/unreadable state; an absent file is a valid empty store.
        self.load()
        try:
            entries = []
            for (root, path), lines in marks.items():
                canonical_root = self._canonical_path(root)
                canonical_file = self._canonical_path(path)
                ordered = sorted(lines)
                if not ordered:
                    continue
                if (not canonical_file.is_relative_to(canonical_root)
                        or len(ordered) > MAX_LINES_PER_FILE
                        or any(type(line) is not int or line <= 0 for line in ordered)):
                    raise ValueError
                entries.append({"root": str(canonical_root), "file": str(canonical_file),
                                "lines": ordered})
            if len(entries) > MAX_BREAKPOINT_FILES:
                raise ValueError
            entries.sort(key=lambda entry: (entry["root"], entry["file"]))
            data = (json.dumps({"version": 1, "breakpoints": entries}, indent=2) + "\n").encode()
            if len(data) > MAX_BREAKPOINT_BYTES:
                raise ValueError
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.path.parent, suffix=".tmp",
                                                 delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        except ConfigurationError:
            raise
        except (OSError, ValueError, TypeError, RuntimeError):
            raise ConfigurationError(
                "Cannot save Code breakpoints; check the projects directory permissions. "
                "The in-memory marks remain available."
            ) from None

    @staticmethod
    def _canonical_path(value) -> Path:
        if isinstance(value, Path):
            value = str(value)
        if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
            raise ValueError
        path = Path(value)
        if not path.is_absolute():
            raise ValueError
        return path.resolve()
