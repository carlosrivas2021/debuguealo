"""Clicking the branch in the Code bar lists local branches and switches with git."""

import json
import os
import shutil
import stat
import sys

import pytest
from test_code_project_store import configure
from test_git_switch import git, make_repo
from test_tui_grouping import Docker, until
from textual.widgets import DataTable, OptionList, TextArea, Tree

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.storage.git_head import current_branch
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.branch_picker import BranchPicker

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

WAIT_FOR_INPUT = "print('READY', flush=True); input()"


def _app(monkeypatch, tmp_path):
    """Profiles: api (repo root) and web (a subfolder of the same repo)."""
    store = configure(monkeypatch, tmp_path)
    repo = make_repo(tmp_path / "repo")
    web = repo / "web"
    web.mkdir()
    store.path.write_text(json.dumps({"version": 1, "configurations": [
        {"name": name, "workspaceFolder": str(root),
         "command": [sys.executable, "-u", "-c", WAIT_FOR_INPUT]}
        for name, root in (("api", repo), ("web", web))
    ]}), encoding="utf-8")
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    return app, repo


def _branch(app):
    label = app.query_one("#code-branch")
    return str(label.render()) if label.display else None


def _messages(app):
    return [item.message for item in app._notifications]


async def _open_picker(pilot, app):
    await pilot.click("#code-branch")
    # Ready once the list has the focus, with the current branch picked.
    await until(pilot, lambda: isinstance(app.screen, BranchPicker)
                and isinstance(app.focused, OptionList))
    return app.focused


async def _choose(pilot, options, name):
    options.highlighted = next(
        i for i in range(options.option_count) if options.get_option_at_index(i).id == name)
    await pilot.press("enter")


async def test_clicking_the_branch_lists_local_branches_with_the_current_one_marked(
        monkeypatch, tmp_path):
    app, _ = _app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        await until(pilot, lambda: _branch(app) == "⎇ main")
        options = await _open_picker(pilot, app)
        labels = [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]
        assert labels == ["  feature/login", "● main"]
        assert options.get_option_at_index(options.highlighted).id == "main"


async def test_choosing_a_branch_switches_the_repo_and_reloads_the_open_file(
        monkeypatch, tmp_path):
    app, repo = _app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        await until(pilot, lambda: _branch(app) == "⎇ main")
        tree = app.query_one("#source-tree", Tree)
        tree.select_node(next(n for n in tree.root.children if str(n.label) == "app.txt"))
        await until(pilot, lambda: app.query_one("#source-text", TextArea).text == "main\n")

        options = await _open_picker(pilot, app)
        await _choose(pilot, options, "feature/login")

        await until(pilot, lambda: _branch(app) == "⎇ feature/login")
        assert current_branch(repo) == "feature/login"
        await until(pilot, lambda: app.query_one("#source-text", TextArea).text == "feature\n")
        assert "Switched to feature/login." in _messages(app)


async def test_escape_closes_the_list_without_switching(monkeypatch, tmp_path):
    app, repo = _app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        await until(pilot, lambda: _branch(app) == "⎇ main")
        await _open_picker(pilot, app)
        await pilot.press("escape")
        await until(pilot, lambda: not isinstance(app.screen, BranchPicker))
        assert current_branch(repo) == "main"
        assert _branch(app) == "⎇ main"


async def test_git_refusal_is_shown_and_nothing_changes(monkeypatch, tmp_path):
    app, repo = _app(monkeypatch, tmp_path)
    (repo / "app.txt").write_text("edited on main\n", encoding="utf-8")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        await until(pilot, lambda: _branch(app) == "⎇ main")
        options = await _open_picker(pilot, app)
        await _choose(pilot, options, "feature/login")

        await until(pilot, lambda: any("Unable to switch to feature/login" in m
                                       for m in _messages(app)))
        assert any("app.txt" in m for m in _messages(app))
        assert current_branch(repo) == "main"
        assert _branch(app) == "⎇ main"
        assert (repo / "app.txt").read_text(encoding="utf-8") == "edited on main\n"


async def test_a_live_profile_in_the_same_repository_blocks_switching(monkeypatch, tmp_path):
    app, repo = _app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        table = app.query_one("#code-projects", DataTable)
        table.move_cursor(row=1)
        table.focus()
        await pilot.press("f5")
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: "READY" in pane.render().plain)
        table.move_cursor(row=0)
        await until(pilot, lambda: _branch(app) == "⎇ main")

        await pilot.click("#code-branch")
        await until(pilot, lambda: "Stop web before switching branches; it runs from this "
                                   "repository." in _messages(app))
        assert not isinstance(app.screen, BranchPicker)
        assert current_branch(repo) == "main"

        table.move_cursor(row=1)
        await pilot.pause()
        await pilot.click("#code-stop")


async def test_a_profile_outside_git_shows_no_branch_to_click(monkeypatch, tmp_path):
    app, repo = _app(monkeypatch, tmp_path)
    git(repo, "branch", "unused")
    # Git keeps its objects read-only, which Windows refuses to delete.
    shutil.rmtree(repo / ".git", onexc=lambda remove, path, _error: (
        os.chmod(path, stat.S_IWRITE), remove(path)))
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        await pilot.pause()
        assert _branch(app) is None


async def test_a_profile_started_while_the_list_is_open_blocks_the_switch(monkeypatch, tmp_path):
    from debugpilot.tui.code_workspace import CodeWorkspace

    app, repo = _app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        await until(pilot, lambda: _branch(app) == "⎇ main")
        options = await _open_picker(pilot, app)
        workspace = app.query_one(CodeWorkspace)
        # web starts from the same repository while the list is open.
        monkeypatch.setattr(workspace, "_profile_status",
                            lambda profile: "run" if profile.name == "web" else None)
        await _choose(pilot, options, "feature/login")

        await until(pilot, lambda: "Stop web before switching branches; it runs from this "
                                   "repository." in _messages(app))
        assert current_branch(repo) == "main"
