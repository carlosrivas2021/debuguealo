"""Best-effort check for a newer debugealo release.

Release tags are read with ``git ls-remote`` from the public repository; every release is
also published to PyPI, where ``uv tool upgrade debugealo`` takes it.
debugealo must keep working offline, so every failure here is silent: the check runs
at most once per CHECK_INTERVAL (failures included), never prompts for credentials,
uses a short timeout, and can be disabled with DEBUGEALO_NO_UPDATE_CHECK=1.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from platformdirs import user_cache_path

from debugpilot import __version__

REPOSITORY_URL = "https://github.com/carlosrivas2021/debuguealo.git"
UPDATE_COMMAND = "uv tool upgrade debugealo"
OPT_OUT_ENV = "DEBUGEALO_NO_UPDATE_CHECK"
CHECK_INTERVAL = timedelta(hours=24)
TIMEOUT_SECONDS = 5.0

_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def cache_path() -> Path:
    return user_cache_path("debugpilot", appauthor=False) / "update-check.json"


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def latest_tag(ls_remote_output: str) -> str | None:
    """Pick the highest vX.Y.Z tag from ``git ls-remote --tags --refs`` output."""
    tags = []
    for line in ls_remote_output.splitlines():
        _, _, ref = line.partition("\t")
        tag = ref.removeprefix("refs/tags/")
        if tag != ref and (version := parse_version(tag)) is not None:
            tags.append((version, tag))
    return max(tags)[1] if tags else None


def fetch_latest_version() -> str | None:
    environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",  # fail instead of asking for a username/password
        "GCM_INTERACTIVE": "never",  # Git Credential Manager must not open a dialog
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
    }
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", REPOSITORY_URL],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=environment,
        timeout=TIMEOUT_SECONDS,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    return latest_tag(result.stdout)


def _read_cache(path: Path, now: datetime) -> tuple[bool, str | None]:
    """Return (fresh, latest) from the cache; anything unreadable counts as stale."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        age = now - datetime.fromisoformat(document["checked_at"])
        latest = document["latest"]
    except (OSError, ValueError, KeyError, TypeError):  # TypeError: naive timestamp
        return False, None
    if latest is not None and not isinstance(latest, str):
        return False, None
    return timedelta(0) <= age < CHECK_INTERVAL, latest


def _write_cache(path: Path, now: datetime, latest: str | None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"checked_at": now.isoformat(), "latest": latest}), encoding="utf-8"
        )
    except OSError:
        pass


def available_update(
    current: str = __version__,
    *,
    now: datetime | None = None,
    fetch: Callable[[], str | None] = fetch_latest_version,
    path: Path | None = None,
) -> str | None:
    """Return the newer released version, or None when up to date or unknown."""
    if os.environ.get(OPT_OUT_ENV) or parse_version(current) is None:
        return None
    now = now or datetime.now(UTC)
    path = path or cache_path()
    fresh, latest = _read_cache(path, now)
    if not fresh:
        try:
            latest = fetch()
        except (OSError, ValueError, subprocess.SubprocessError):
            latest = None  # no git, offline, timeout, no credentials or a bad response
        _write_cache(path, now, latest)
    newest = parse_version(latest) if latest else None
    if newest is None or newest <= parse_version(current):
        return None
    return ".".join(str(part) for part in newest)
