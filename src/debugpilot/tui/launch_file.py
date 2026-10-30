"""Edit the workspace launch file in the caller's terminal."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from debugpilot.core.exceptions import ConfigurationError


def open_launch_file(path: Path) -> None:
    """Wait for nano (or vi) to exit, inheriting the suspended TUI's terminal."""
    try:
        target = Path(path).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise ConfigurationError(
            "Cannot open launch.json because the file is unavailable."
        ) from None
    if not target.is_file():
        raise ConfigurationError("Cannot open launch.json because the target is not a file.")

    editor = shutil.which("nano") or shutil.which("vi")
    if editor is None:
        raise ConfigurationError("Install nano or vi on PATH to edit launch.json in this terminal.")
    try:
        # No timeout or redirected streams: the editor owns the terminal until exit.
        result = subprocess.run([editor, str(target)], shell=False, check=False)
    except OSError:
        raise ConfigurationError(f"Could not start the terminal editor for {target}.") from None
    if result.returncode != 0:
        raise ConfigurationError(
            f"The terminal editor exited with status {result.returncode}; "
            "check launch.json before retrying."
        )
