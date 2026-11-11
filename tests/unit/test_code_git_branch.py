"""The Code bar shows the selected profile's Git branch, frozen at launch while it runs."""

import json
import sys

from test_code_project_store import configure
from test_tui_grouping import Docker, until
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp

WAIT_FOR_INPUT = "print('READY', flush=True); input()"


def _checkout(root, branch):
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")


def _app(monkeypatch, tmp_path):
    store = configure(monkeypatch, tmp_path)
    repo, plain = tmp_path / "repo", tmp_path / "plain"
    repo.mkdir()
    plain.mkdir()
    _checkout(repo, "main")
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "configurations": [
                    {
                        "name": name,
                        "workspaceFolder": str(root),
                        "command": [sys.executable, "-u", "-c", WAIT_FOR_INPUT],
                    }
                    for name, root in (("repo", repo), ("plain", plain))
                ],
            }
        ),
        encoding="utf-8",
    )
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    return app, repo


def _branch(app):
    label = app.query_one("#code-branch")
    return str(label.render()) if label.display else None


async def test_selected_profile_shows_its_branch_and_none_without_git(monkeypatch, tmp_path):
    app, _repo = _app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        await pilot.pause()
        assert _branch(app) == "⎇ main"
        app.query_one("#code-projects", DataTable).move_cursor(row=1)
        await pilot.pause()
        assert _branch(app) is None
        # The idle profile reads the branch again, so a checkout shows up on reselection.
        _checkout(_repo, "feature/login")
        app.query_one("#code-projects", DataTable).move_cursor(row=0)
        await pilot.pause()
        assert _branch(app) == "⎇ feature/login"


async def test_running_profile_keeps_its_launch_branch_until_relaunched(monkeypatch, tmp_path):
    app, repo = _app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        table = app.query_one("#code-projects", DataTable)
        table.focus()
        await pilot.press("f5")
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: "READY" in pane.render().plain)

        _checkout(repo, "hotfix")
        table.move_cursor(row=1)
        await pilot.pause()
        table.move_cursor(row=0)
        await pilot.pause()
        assert _branch(app) == "⎇ main"

        await pilot.click("#code-stop")
        await until(pilot, lambda: "Stopped" in str(app.query_one("#code-run-state").render()))
        assert _branch(app) == "⎇ hotfix"

        table.focus()
        await pilot.press("f5")
        await until(pilot, lambda: "READY" in pane.render().plain)
        _checkout(repo, "later")
        await pilot.pause()
        assert _branch(app) == "⎇ hotfix"
        await pilot.click("#code-stop")
