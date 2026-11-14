"""Load and save small text files for the in-app editor: atomic and conflict-aware."""

from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from debugpilot.core.exceptions import ConfigurationError

MAX_TEXT_BYTES = 1024 * 1024
# Files this editor creates may hold credentials, so new ones are private.
NEW_FILE_MODE = 0o600
NEW_DIRECTORY_MODE = 0o700


@dataclass(frozen=True)
class LoadedText:
    """What the editor opened: the real target and the on-disk state it saw."""

    path: Path
    text: str
    signature: tuple[int, int, int, int, int] | None

    @property
    def exists(self) -> bool:
        return self.signature is not None


def _target(path: Path) -> Path:
    # A symlinked dotfile is written through, so the link itself is kept.
    return Path(path).expanduser().resolve(strict=False)


def _signature(path: Path) -> tuple[int, int, int, int, int] | None:
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(f"{path} is not a regular file.")
    # ctime catches a write that restored the old size and mtime.
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns,
            metadata.st_ctime_ns)


def load_text(path: Path) -> LoadedText:
    target = _target(path)
    try:
        before = _signature(target)
        if before is None:
            return LoadedText(target, "", None)
        if before[2] > MAX_TEXT_BYTES:
            raise ConfigurationError(f"{target} is larger than {MAX_TEXT_BYTES // 1024} KiB.")
        data = target.read_bytes()
        if _signature(target) != before:
            raise ConfigurationError(f"{target} changed while being read; open it again.")
    except OSError as error:
        raise ConfigurationError(f"Cannot read {target}: {error.strerror or error}") from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigurationError(f"{target} is not UTF-8 text.") from None
    return LoadedText(target, text, before)


def save_text(loaded: LoadedText, text: str) -> LoadedText:
    """Replace the file atomically, refusing if it changed since it was opened."""
    target = loaded.path
    data = text.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise ConfigurationError(f"The text is larger than {MAX_TEXT_BYTES // 1024} KiB.")
    conflict = ConfigurationError(
        f"{target} changed on disk since it was opened; your edits were not saved."
    )
    temporary: Path | None = None
    try:
        if _signature(target) != loaded.signature:
            raise conflict
        target.parent.mkdir(mode=NEW_DIRECTORY_MODE, parents=True, exist_ok=True)
        mode = stat.S_IMODE(target.stat().st_mode) if loaded.exists else NEW_FILE_MODE
        descriptor, name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        # Checked again right before the replace, so a save from elsewhere is never lost.
        if _signature(target) != loaded.signature or (
            loaded.exists and target.read_bytes() != loaded.text.encode("utf-8")
        ):
            raise conflict
        os.replace(temporary, target)
        temporary = None
        return LoadedText(target, text, _signature(target))
    except OSError as error:
        raise ConfigurationError(f"Cannot save {target}: {error.strerror or error}") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
