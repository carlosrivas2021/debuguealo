"""Persistent watch expressions per Code project root, separate from breakpoints."""

import json
import os
import tempfile
from pathlib import Path

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.config import config_path

MAX_WATCH_BYTES = 256 * 1024
MAX_WATCH_ROOTS = 4096
MAX_WATCHES_PER_ROOT = 100
MAX_WATCH_CHARS = 1000


def watch_expression(value) -> str:
    """Normalize one expression from the editor; blank, NUL or overlong text is invalid."""
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("Watch expressions must be text.")
    value = value.strip()
    if not value:
        raise ValueError("Enter an expression to watch.")
    if len(value) > MAX_WATCH_CHARS:
        raise ValueError("Watch expressions are limited to 1000 characters.")
    return value


class WatchStore:
    """Store ordered watch expressions per project root; values are never persisted."""

    def __init__(self, path: Path | None = None):
        self.path = (
            path if path is not None
            else config_path().parent / "projects" / "watches.json"
        )

    def load(self) -> dict[Path, tuple[str, ...]]:
        try:
            with self.path.open("rb") as stream:
                data = stream.read(MAX_WATCH_BYTES + 1)
        except FileNotFoundError:
            return {}
        except OSError:
            raise ConfigurationError(
                "Cannot read watch expressions; check the projects directory permissions."
            ) from None
        try:
            if len(data) > MAX_WATCH_BYTES:
                raise ValueError
            document = json.loads(data)
            if (not isinstance(document, dict) or set(document) != {"version", "watches"}
                    or type(document["version"]) is not int or document["version"] != 1):
                raise ValueError
            entries = document["watches"]
            if not isinstance(entries, list) or len(entries) > MAX_WATCH_ROOTS:
                raise ValueError
            watches = {}
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {"root", "expressions"}:
                    raise ValueError
                root = self._canonical_root(entry["root"])
                expressions = entry["expressions"]
                if (not isinstance(expressions, list) or not expressions
                        or len(expressions) > MAX_WATCHES_PER_ROOT or root in watches):
                    raise ValueError
                watches[root] = tuple(watch_expression(value) for value in expressions)
            return watches
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OSError,
                RuntimeError):
            raise ConfigurationError(
                "Invalid watch expressions; repair projects/watches.json. "
                "The existing file was not changed."
            ) from None

    def save(self, watches: dict[Path, list[str]]) -> None:
        # Refuse to replace invalid/unreadable state; an absent file is a valid empty store.
        self.load()
        try:
            entries = []
            for root, expressions in watches.items():
                if not expressions:
                    continue
                if len(expressions) > MAX_WATCHES_PER_ROOT:
                    raise ValueError
                entries.append({
                    "root": str(self._canonical_root(root)),
                    "expressions": [watch_expression(value) for value in expressions],
                })
            if len(entries) > MAX_WATCH_ROOTS:
                raise ValueError
            entries.sort(key=lambda entry: entry["root"])
            data = (json.dumps({"version": 1, "watches": entries}, indent=2) + "\n").encode()
            if len(data) > MAX_WATCH_BYTES:
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
                "Cannot save watch expressions; check the projects directory permissions. "
                "The current watches remain available."
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
