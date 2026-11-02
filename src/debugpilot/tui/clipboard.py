"""Native clipboard fallback for terminals that ignore OSC 52 (macOS Terminal, Warp...)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

_TIMEOUT_SECONDS = 2


def _native_command() -> list[str] | None:
    """Return a local clipboard writer, or None when only the terminal can help."""
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        # A remote host's clipboard is not the user's; rely on OSC 52 only.
        return None
    candidates: list[list[str]] = []
    if sys.platform == "darwin":
        candidates.append(["pbcopy"])
    elif sys.platform == "win32":
        candidates.append(["clip"])
    else:
        if os.environ.get("WAYLAND_DISPLAY"):
            candidates.append(["wl-copy"])
        if os.environ.get("DISPLAY"):
            candidates.extend((["xclip", "-selection", "clipboard"], ["xsel", "-ib"]))
        candidates.append(["clip.exe"])  # WSL
    for command in candidates:
        executable = shutil.which(command[0])
        if executable is not None:
            return [executable, *command[1:]]
    return None


def copy_native(text: str) -> bool:
    """Best-effort copy through the OS clipboard; never raises."""
    command = _native_command()
    if command is None:
        return False
    try:
        result = subprocess.run(
            command,
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return result.returncode == 0
