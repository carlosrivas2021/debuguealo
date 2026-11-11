"""Reading the checked-out Git branch of a project root without running git."""

from debugpilot.storage.git_head import current_branch


def _repo(root, head):
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(head, encoding="utf-8")
    return root


def test_branch_name_from_symbolic_ref(tmp_path):
    _repo(tmp_path, "ref: refs/heads/feature/login\n")
    assert current_branch(tmp_path) == "feature/login"


def test_detached_head_shows_short_commit(tmp_path):
    _repo(tmp_path, "0123456789abcdef0123456789abcdef01234567\n")
    assert current_branch(tmp_path) == "detached @ 0123456"


def test_project_inside_a_repository_uses_the_enclosing_head(tmp_path):
    _repo(tmp_path, "ref: refs/heads/main\n")
    nested = tmp_path / "services" / "api"
    nested.mkdir(parents=True)
    assert current_branch(nested) == "main"


def test_worktree_git_file_points_to_its_own_head(tmp_path):
    gitdir = tmp_path / "main-repo" / ".git" / "worktrees" / "hotfix"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/hotfix\n", encoding="utf-8")
    worktree = tmp_path / "hotfix"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    assert current_branch(worktree) == "hotfix"


def test_relative_worktree_gitdir_resolves_from_the_worktree(tmp_path):
    gitdir = tmp_path / "repo" / ".git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/wt-branch\n", encoding="utf-8")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: ../repo/.git/worktrees/wt\n", encoding="utf-8")
    assert current_branch(worktree) == "wt-branch"


def test_folder_without_git_has_no_branch(tmp_path):
    project = tmp_path / "plain"
    project.mkdir()
    assert current_branch(project, stop_at=tmp_path) is None


def test_missing_root_has_no_branch(tmp_path):
    assert current_branch(tmp_path / "gone") is None


def test_unreadable_or_unexpected_head_has_no_branch(tmp_path):
    _repo(tmp_path / "garbage", "not a ref\n")
    _repo(tmp_path / "huge", "ref: refs/heads/" + "x" * 5000)
    (tmp_path / "nohead" / ".git").mkdir(parents=True)
    assert current_branch(tmp_path / "garbage") is None
    assert current_branch(tmp_path / "huge") is None
    assert current_branch(tmp_path / "nohead") is None
