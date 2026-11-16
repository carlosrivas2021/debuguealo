"""Where the debugger pauses on exceptions, per Code project root."""

import json
import os
import tempfile
from pathlib import Path

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.config import config_path

# Where the debugger pauses on exceptions: uncaught ones, every raised one, or never.
EXCEPTION_MODES = ("uncaught", "all", "none")
DEFAULT_EXCEPTION_MODE = "uncaught"
MAX_EXCEPTION_BYTES = 256 * 1024
MAX_EXCEPTION_ROOTS = 4096


class ExceptionModeStore:
    """Store each project's exception mode; the default mode is never written."""

    def __init__(self, path: Path | None = None):
        self.path = (
            path if path is not None
            else config_path().parent / "projects" / "exceptions.json"
        )

    def load(self) -> dict[Path, str]:
        try:
            with self.path.open("rb") as stream:
                data = stream.read(MAX_EXCEPTION_BYTES + 1)
        except FileNotFoundError:
            return {}
        except OSError:
            raise ConfigurationError(
                "Cannot read exception settings; check the projects directory permissions."
            ) from None
        try:
            if len(data) > MAX_EXCEPTION_BYTES:
                raise ValueError
            document = json.loads(data)
            if (not isinstance(document, dict) or set(document) != {"version", "modes"}
                    or type(document["version"]) is not int or document["version"] != 1):
                raise ValueError
            entries = document["modes"]
            if not isinstance(entries, list) or len(entries) > MAX_EXCEPTION_ROOTS:
                raise ValueError
            modes = {}
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {"root", "mode"}:
                    raise ValueError
                root = self._canonical_root(entry["root"])
                if entry["mode"] not in EXCEPTION_MODES or root in modes:
                    raise ValueError
                modes[root] = entry["mode"]
            return modes
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OSError,
                RuntimeError):
            raise ConfigurationError(
                "Invalid exception settings; repair projects/exceptions.json. "
                "The existing file was not changed."
            ) from None

    def save(self, modes: dict[Path, str]) -> None:
        # Refuse to replace invalid/unreadable state; an absent file is a valid empty store.
        self.load()
        try:
            entries = []
            for root, mode in modes.items():
                if mode not in EXCEPTION_MODES:
                    raise ValueError
                if mode == DEFAULT_EXCEPTION_MODE:
                    continue
                entries.append({"root": str(self._canonical_root(root)), "mode": mode})
            if len(entries) > MAX_EXCEPTION_ROOTS:
                raise ValueError
            entries.sort(key=lambda entry: entry["root"])
            data = (json.dumps({"version": 1, "modes": entries}, indent=2) + "\n").encode()
            if len(data) > MAX_EXCEPTION_BYTES:
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
                "Cannot save exception settings; check the projects directory permissions. "
                "The current setting stays in effect until Debugealo closes."
            ) from None

    @staticmethod
    def _canonical_root(value) -> Path:
        if isinstance(value, Path):
            value = str(value)
        if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
            raise ValueError
        path = Path(value)
        if not path.is_absolute():
            raise ValueError
        return path.resolve()
