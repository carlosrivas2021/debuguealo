"""Listing a project's files and searching their text, for F in Code."""

import os

import pytest

from debugpilot.storage.project_files import (
    TextMatch,
    matching_files,
    project_files,
    search_text,
)


def write(root, relative, content="x\n"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def test_files_are_listed_relative_and_sorted_without_tool_folders(tmp_path):
    for relative in ("main.py", "orders/models.py", "orders/views.py", ".env",
                     ".github/workflows/ci.yml", ".git/config", "node_modules/a/index.js",
                     "pkg/__pycache__/m.pyc", ".venv/lib/site.py", "venv/lib/site.py"):
        write(tmp_path, relative)
    files, truncated = project_files(tmp_path)
    assert files == [".env", ".github/workflows/ci.yml", "main.py", "orders/models.py",
                     "orders/views.py"]
    assert truncated is False


def test_links_are_never_followed(tmp_path):
    write(tmp_path, "main.py")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    write(outside, "secret.py")
    try:
        os.symlink(outside, tmp_path / "linked", target_is_directory=True)
        os.symlink(outside / "secret.py", tmp_path / "secret.py")
    except OSError:
        pytest.skip("symbolic links are not available")
    assert project_files(tmp_path) == (["main.py"], False)


def test_a_huge_project_is_cut_at_the_limit(tmp_path):
    for index in range(5):
        write(tmp_path, f"f{index}.py")
    files, truncated = project_files(tmp_path, limit=3)
    assert len(files) == 3 and truncated is True


def test_file_names_match_before_folders_then_letters_in_order():
    files = ["docs/orders.md", "orders/models.py", "orders/views.py", "src/order_total.py",
             "tests/test_orders.py", "other/readme.md"]
    # The name starting with the query, then containing it, then the path, then in order.
    assert matching_files("ord", files) == [
        "docs/orders.md", "src/order_total.py", "tests/test_orders.py",
        "orders/models.py", "orders/views.py", "other/readme.md"]
    assert matching_files("omod", files) == ["orders/models.py"]
    assert matching_files("  ", files) == files
    assert matching_files("ORDER_T", files) == ["src/order_total.py"]


def test_text_search_finds_lines_ignoring_case(tmp_path):
    write(tmp_path, "a.py", "total = 1\nprint(Total)\n")
    write(tmp_path, "b/c.py", "nothing here\n    subtotal += 2\n")
    files, _ = project_files(tmp_path)
    matches, truncated = search_text(tmp_path, files, "total")
    assert matches == [
        TextMatch("a.py", 1, "total = 1"),
        TextMatch("a.py", 2, "print(Total)"),
        TextMatch("b/c.py", 2, "subtotal += 2"),
    ]
    assert truncated is False


def test_text_search_skips_binary_and_large_files_and_reads_other_encodings(tmp_path):
    write(tmp_path, "image.png", b"\x89PNG\x00total")
    write(tmp_path, "big.log", "total\n" * 300_000)  # Over 1 MiB.
    write(tmp_path, "latin.txt", "total caf\xe9\n".encode("latin-1"))
    files, _ = project_files(tmp_path)
    matches, _ = search_text(tmp_path, files, "total")
    assert matches == [TextMatch("latin.txt", 1, "total caf\N{REPLACEMENT CHARACTER}")]


def test_text_search_stops_at_the_limit_and_when_told(tmp_path):
    write(tmp_path, "a.py", "hit\n" * 10)
    write(tmp_path, "b.py", "hit\n")
    files, _ = project_files(tmp_path)
    matches, truncated = search_text(tmp_path, files, "hit", limit=4)
    assert len(matches) == 4 and truncated is True
    assert search_text(tmp_path, files, "hit", should_stop=lambda: True) == ([], False)


def test_long_lines_are_shortened_and_a_vanished_file_is_skipped(tmp_path):
    write(tmp_path, "long.py", "x" * 500 + " needle\n")
    files, _ = project_files(tmp_path)
    matches, _ = search_text(tmp_path, [*files, "gone.py"], "needle")
    assert len(matches) == 1 and len(matches[0].text) <= 200
    assert matches[0].text.endswith("…")
