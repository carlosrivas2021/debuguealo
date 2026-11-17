"""The color theme chosen in the app (Ctrl+P → Theme), remembered between sessions."""

import json
import os
import re
import tempfile
from pathlib import Path

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.config import config_path

MAX_THEME_BYTES = 4096
# Textual theme names: lowercase words joined by dashes, such as "tokyo-night".
_THEME_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class ThemeStore:
    """Store one theme name beside the other settings; config.toml stays hand-edited."""

    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else config_path().parent / "theme.json"

    def load(self) -> str | None:
        """The saved theme name, or None when none was chosen yet."""
        try:
            with self.path.open("rb") as stream:
                data = stream.read(MAX_THEME_BYTES + 1)
        except FileNotFoundError:
            return None
        except OSError:
            raise ConfigurationError(
                "Cannot read the saved theme; check the settings directory permissions."
            ) from None
        try:
            if len(data) > MAX_THEME_BYTES:
                raise ValueError
            document = json.loads(data)
            if (not isinstance(document, dict) or set(document) != {"version", "theme"}
                    or type(document["version"]) is not int or document["version"] != 1
                    or not isinstance(document["theme"], str)
                    or not _THEME_NAME.fullmatch(document["theme"])):
                raise ValueError
            return document["theme"]
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ConfigurationError(
                "Invalid saved theme; repair or delete theme.json. "
                "The existing file was not changed."
            ) from None

    def save(self, theme: str) -> None:
        # Refuse to replace invalid/unreadable state; an absent file is a valid empty store.
        self.load()
        try:
            if not isinstance(theme, str) or not _THEME_NAME.fullmatch(theme):
                raise ValueError
            data = (json.dumps({"version": 1, "theme": theme}, indent=2) + "\n").encode()
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
                "Cannot save the theme; check the settings directory permissions. "
                "It stays in effect until Debugealo closes."
            ) from None
