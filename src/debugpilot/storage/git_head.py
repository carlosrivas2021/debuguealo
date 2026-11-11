"""Read the checked-out Git branch of a folder from disk, without running git."""

import re
from pathlib import Path

# HEAD and a worktree's .git file are tiny; anything larger is not a Git file.
MAX_FILE_BYTES = 1024
_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_BRANCH_PREFIX = "ref: refs/heads/"


def current_branch(root: Path, *, stop_at: Path | None = None) -> str | None:
    """Return the branch checked out for ``root``, or None outside a readable repository.

    ``root`` may be a subfolder of the repository. A detached HEAD reads as
    ``detached @ <short commit>``. ``stop_at`` bounds the upward search.
    """
    try:
        start = Path(root).resolve(strict=True)
        limit = Path(stop_at).resolve() if stop_at is not None else None
    except (OSError, RuntimeError):
        return None
    for folder in (start, *start.parents):
        marker = folder / ".git"
        if marker.is_dir():
            return _branch(marker)
        if marker.is_file():
            git_dir = _worktree_git_dir(marker)
            return _branch(git_dir) if git_dir is not None else None
        if folder == limit:
            break
    return None


def _branch(git_dir: Path) -> str | None:
    head = _read(git_dir / "HEAD")
    if head is None:
        return None
    if head.startswith(_BRANCH_PREFIX):
        name = head.removeprefix(_BRANCH_PREFIX)
        return name if name and name.isprintable() and " " not in name else None
    if _COMMIT.fullmatch(head):
        return f"detached @ {head[:7]}"
    return None


def _worktree_git_dir(marker: Path) -> Path | None:
    content = _read(marker)
    if content is None or not content.startswith("gitdir: "):
        return None
    git_dir = Path(content.removeprefix("gitdir: "))
    return git_dir if git_dir.is_absolute() else marker.parent / git_dir


def _read(path: Path) -> str | None:
    try:
        with path.open("rb") as source:
            data = source.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_FILE_BYTES:
        return None
    try:
        return data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
