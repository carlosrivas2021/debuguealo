"""A project's files and the lines that hold some text, for finding things with F in Code.

Both read the disk and can take a while on a big project, so callers run them in a thread.
Links are never followed (like the file tree), and tool folders that hold no project code
of their own are skipped.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from debugpilot.core.fuzzy import letters_in_order

MAX_FILES = 50_000
MAX_MATCHES = 500
# Like the source preview: larger files are logs or data, not code to read.
MAX_SEARCH_BYTES = 1024 * 1024
MAX_LINE_CHARS = 200
SKIPPED_FOLDERS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
})


@dataclass(frozen=True)
class TextMatch:
    path: str  # Relative to the project, with forward slashes.
    line: int  # 1-based.
    text: str  # The line, trimmed and shortened.


def project_files(root: Path, limit: int = MAX_FILES) -> tuple[list[str], bool]:
    """The project's files relative to ``root``, sorted, and whether ``limit`` cut them."""
    files = []
    pending = [Path(root)]
    while pending:
        folder = pending.pop()
        try:
            with os.scandir(folder) as listing:
                entries = list(listing)
        except OSError:
            continue  # Unreadable folders are left out, as in the file tree.
        for entry in entries:
            try:
                if entry.is_symlink() or entry.is_junction():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in SKIPPED_FOLDERS:
                        pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    files.append(Path(entry.path).relative_to(root).as_posix())
                    if len(files) > limit:
                        return sorted(files[:limit]), True
            except OSError:
                continue
    return sorted(files), False


def matching_files(query: str, files: list[str]) -> list[str]:
    """Files that look like the query, best first: the file name starting with it, then
    containing it, then the path containing it, then the path holding its letters in order
    (``omod`` finds ``orders/models.py``); the list order breaks ties.
    """
    query = query.strip().casefold()
    if not query:
        return list(files)
    ranked = []
    for index, path in enumerate(files):
        folded = path.casefold()
        name = folded.rsplit("/", 1)[-1]
        if name.startswith(query):
            rank = 0
        elif query in name:
            rank = 1
        elif query in folded:
            rank = 2
        elif letters_in_order(query, folded):
            rank = 3
        else:
            continue
        ranked.append((rank, index, path))
    return [path for _rank, _index, path in sorted(ranked)]


def search_text(
    root: Path,
    files: list[str],
    query: str,
    limit: int = MAX_MATCHES,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[list[TextMatch], bool]:
    """Lines of ``files`` that contain ``query``, ignoring case, and whether ``limit`` cut
    them. Binary files and files over 1 MiB are skipped. ``should_stop`` is asked before each
    file, so a newer search can end this one early.
    """
    needle = query.casefold()
    matches = []
    for relative in files:
        if should_stop is not None and should_stop():
            return [], False
        path = Path(root, relative)
        try:
            if path.stat().st_size > MAX_SEARCH_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue  # Gone or unreadable since it was listed.
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        if needle not in text.casefold():
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.casefold():
                matches.append(TextMatch(relative, number, _shortened(line.strip())))
                if len(matches) >= limit:
                    return matches, True
    return matches, False


def _shortened(line: str) -> str:
    if len(line) <= MAX_LINE_CHARS:
        return line
    return line[: MAX_LINE_CHARS - 1] + "…"
