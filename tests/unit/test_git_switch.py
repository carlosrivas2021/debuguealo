"""Listing local branches and switching between them with the real git command."""

import shutil
import subprocess
import sys

import pytest

from debugpilot.storage import git_branches
from debugpilot.storage.git_branches import (
    GitError,
    local_branches,
    repository_root,
    switch_branch,
)
from debugpilot.storage.git_head import current_branch

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(root, *args):
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=root, check=True, capture_output=True,
    )


def make_repo(root):
    """A repository on main with app.txt, plus a feature branch that changes it."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    (root / "app.txt").write_text("main\n", encoding="utf-8")
    git(root, "add", "app.txt")
    git(root, "commit", "-q", "-m", "main")
    git(root, "switch", "-q", "-c", "feature/login")
    (root / "app.txt").write_text("feature\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "feature")
    git(root, "switch", "-q", "main")
    return root


def test_lists_local_branches_sorted(tmp_path):
    repo = make_repo(tmp_path / "repo")
    git(repo, "branch", "bugfix")

    assert local_branches(repo) == ["bugfix", "feature/login", "main"]


def test_switch_checks_out_the_branch(tmp_path):
    repo = make_repo(tmp_path / "repo")

    switch_branch(repo, "feature/login")

    assert current_branch(repo) == "feature/login"
    assert (repo / "app.txt").read_text(encoding="utf-8") == "feature\n"


def test_switch_from_a_subfolder_uses_the_enclosing_repository(tmp_path):
    repo = make_repo(tmp_path / "repo")
    nested = repo / "services" / "api"
    nested.mkdir(parents=True)

    assert repository_root(nested) == repo.resolve()
    switch_branch(nested, "feature/login")

    assert current_branch(repo) == "feature/login"


def test_uncommitted_change_that_does_not_conflict_is_carried_along(tmp_path):
    repo = make_repo(tmp_path / "repo")
    (repo / "notes.txt").write_text("draft\n", encoding="utf-8")

    switch_branch(repo, "feature/login")

    assert current_branch(repo) == "feature/login"
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "draft\n"


def test_conflicting_change_is_refused_with_gits_message_and_nothing_changes(tmp_path):
    repo = make_repo(tmp_path / "repo")
    (repo / "app.txt").write_text("edited on main\n", encoding="utf-8")

    with pytest.raises(GitError, match="app.txt"):
        switch_branch(repo, "feature/login")

    assert current_branch(repo) == "main"
    assert (repo / "app.txt").read_text(encoding="utf-8") == "edited on main\n"


@pytest.mark.parametrize("name", ["missing", "--orphan", "-"])
def test_only_existing_local_branches_can_be_switched_to(tmp_path, name):
    repo = make_repo(tmp_path / "repo")

    with pytest.raises(GitError, match="No local branch named"):
        switch_branch(repo, name)

    assert current_branch(repo) == "main"


def test_folder_outside_a_repository_reports_git_error(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(GitError):
        local_branches(plain)


def test_missing_git_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(GitError, match="git is not installed"):
        local_branches(tmp_path)


def test_branch_sharing_a_name_with_a_tag_is_listed_by_its_plain_name(tmp_path):
    repo = make_repo(tmp_path / "repo")
    git(repo, "tag", "main")

    assert local_branches(repo) == ["feature/login", "main"]


@pytest.mark.skipif(sys.platform == "win32", reason="the hook is a POSIX shell script")
def test_a_slow_switch_is_not_cut_short_by_the_query_timeout(tmp_path, monkeypatch):
    """Killing git mid-checkout could leave a half-updated tree, so switch has no timeout."""
    repo = make_repo(tmp_path / "repo")
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text("#!/bin/sh\nsleep 2\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setattr(git_branches, "TIMEOUT_SECONDS", 1)

    switch_branch(repo, "feature/login")

    assert current_branch(repo) == "feature/login"
