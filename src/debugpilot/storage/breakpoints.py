"""Persistent requested Code breakpoint intent, separate from launch profiles."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.config import config_path

MAX_BREAKPOINT_BYTES = 256 * 1024
MAX_BREAKPOINT_FILES = 4096
MAX_LINES_PER_FILE = 100_000
MAX_OPTION_CHARS = 1000
# Persisted field names follow DAP's SourceBreakpoint.
_OPTION_FIELDS = {"condition": "condition", "logMessage": "log_message"}


@dataclass(frozen=True)
class BreakpointOptions:
    """A condition and/or a log message (logpoint) for one breakpoint line."""

    condition: str | None = None
    log_message: str | None = None


def _option_text(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("Breakpoint conditions and log messages must be text.")
    value = value.strip()
    if len(value) > MAX_OPTION_CHARS:
        raise ValueError("Breakpoint conditions and log messages are limited to 1000 characters.")
    return value or None


def breakpoint_options(condition, log_message) -> BreakpointOptions | None:
    """Normalize editor input; blank fields mean a plain breakpoint (None)."""
    options = BreakpointOptions(_option_text(condition), _option_text(log_message))
    return options if options.condition or options.log_message else None


class BreakpointStore:
    """Store requested line marks centrally; debugger verification is never persisted."""

    def __init__(self, path: Path | None = None):
        self.path = (
            path if path is not None
            else config_path().parent / "projects" / "breakpoints.json"
        )

    def load(self) -> dict[tuple[Path, Path], tuple[int, ...]]:
        return self._read()[0]

    def load_options(self) -> dict[tuple[Path, Path], dict[int, BreakpointOptions]]:
        """Per-line options of the stored marks; entries without options are absent."""
        return self._read()[1]

    def _read(self):
        try:
            with self.path.open("rb") as stream:
                data = stream.read(MAX_BREAKPOINT_BYTES + 1)
        except FileNotFoundError:
            return {}, {}
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
            marks, options = {}, {}
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) - {"options"} != {
                        "root", "file", "lines"}:
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
                if "options" in entry:
                    options[key] = self._parse_options(entry["options"], lines)
            return marks, options
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OSError,
                RuntimeError):
            raise ConfigurationError(
                "Invalid Code breakpoints; repair projects/breakpoints.json. "
                "The existing file was not changed."
            ) from None

    @staticmethod
    def _parse_options(value, lines) -> dict[int, BreakpointOptions]:
        if not isinstance(value, dict) or not value:
            raise ValueError
        parsed = {}
        for key, fields in value.items():
            # Canonical ASCII line numbers only: "05" or non-ASCII digits are rejected.
            if (not isinstance(key, str) or not key.isascii() or not key.isdigit()
                    or key != str(int(key)) or int(key) not in lines):
                raise ValueError
            if not isinstance(fields, dict) or not fields or set(fields) - set(_OPTION_FIELDS):
                raise ValueError
            if any(not isinstance(text, str) or not text.strip() for text in fields.values()):
                raise ValueError
            parsed[int(key)] = breakpoint_options(
                fields.get("condition"), fields.get("logMessage"))
        return parsed

    @staticmethod
    def _serialize_options(line_options, lines) -> dict[str, dict[str, str]]:
        serialized = {}
        for line in sorted(line_options):
            option = line_options[line]
            if line not in lines or option is None:
                continue
            # Re-validate through the editor normalization before publishing.
            option = breakpoint_options(option.condition, option.log_message)
            if option is None:
                continue
            serialized[str(line)] = {
                name: getattr(option, attribute) for name, attribute in _OPTION_FIELDS.items()
                if getattr(option, attribute)
            }
        return serialized

    def save(
        self,
        marks: dict[tuple[Path, Path], set[int]],
        options: dict[tuple[Path, Path], dict[int, BreakpointOptions]] | None = None,
    ) -> None:
        # Refuse to replace invalid/unreadable state; an absent file is a valid empty store.
        self.load()
        try:
            canonical_options = {}
            for (root, path), line_options in (options or {}).items():
                try:
                    key = (self._canonical_path(root), self._canonical_path(path))
                except ValueError:
                    # Unusable paths can never match a stored mark; their options are dropped.
                    continue
                canonical_options.setdefault(key, {}).update(line_options)
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
                entry = {"root": str(canonical_root), "file": str(canonical_file),
                         "lines": ordered}
                serialized = self._serialize_options(
                    canonical_options.get((canonical_root, canonical_file), {}), set(ordered))
                if serialized:
                    entry["options"] = serialized
                entries.append(entry)
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
