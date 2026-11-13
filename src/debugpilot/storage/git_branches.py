"""List local branches and switch between them by running git in a project folder."""

import os
import subprocess
import sys
from pathlib import Path

TIMEOUT_SECONDS = 15


class GitError(Exception):
    """git could not run or refused the operation; the message is shown to the user."""


def _git(root: Path, *arguments: str, bounded: bool = True) -> str:
    environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",  # fail instead of asking for a username/password
        "GCM_INTERACTIVE": "never",  # Git Credential Manager must not open a dialog
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
    }
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=environment,
            timeout=TIMEOUT_SECONDS if bounded else None,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except FileNotFoundError:
        raise GitError("git is not installed or not on PATH.") from None
    except subprocess.TimeoutExpired:
        raise GitError(f"git did not finish within {TIMEOUT_SECONDS} seconds.") from None
    except OSError as error:
        raise GitError(f"Unable to run git: {error}") from None
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git exited with code {result.returncode}.")
    return result.stdout


def repository_root(root: Path) -> Path:
    """The top folder of the repository that contains ``root``."""
    return Path(_git(root, "rev-parse", "--show-toplevel").strip()).resolve()


def local_branches(root: Path) -> list[str]:
    # lstrip keeps the plain name even when a tag shares it (short would say heads/<name>).
    output = _git(root, "for-each-ref", "--format=%(refname:lstrip=2)", "refs/heads")
    return sorted(line for line in output.splitlines() if line)


def switch_branch(root: Path, name: str) -> None:
    """Check out an existing local branch, leaving uncommitted changes to git's rules.

    git carries changes that do not conflict with the target branch and refuses the switch,
    changing nothing, when they do.
    """
    # Only names git itself listed, so a name can never be read as an option.
    if name.startswith("-") or name not in local_branches(root):
        raise GitError(f"No local branch named {name}.")
    # No timeout: killing git mid-checkout could leave a half-updated tree and a stale
    # index.lock. It runs in a background worker, so a slow hook only delays the result.
    _git(root, "switch", name, bounded=False)
