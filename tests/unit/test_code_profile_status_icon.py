"""Each Code profile row shows whether it runs or debugs; no icon means stopped."""

import json
import sys

from test_code_project_store import configure
from test_tui_grouping import Docker, until
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp

WAIT_FOR_INPUT = "print('READY', flush=True); input()"
EXIT_SOON = "import time; print('READY', flush=True); time.sleep(1.5)"
SLEEP = "import time; time.sleep(30)"


def _app(monkeypatch, tmp_path, first_script):
    store = configure(monkeypatch, tmp_path)
    configurations = []
    for name, script in (("alpha", first_script), ("beta", WAIT_FOR_INPUT)):
        root = tmp_path / name
        root.mkdir()
        # A script file, because Python debugging does not accept `-c`.
        (root / "main.py").write_text(script, encoding="utf-8")
        configurations.append(
            {
                "name": name,
                "workspaceFolder": str(root),
                "command": [sys.executable, "-u", "main.py"],
            }
        )
    store.path.write_text(
        json.dumps({"version": 1, "configurations": configurations}), encoding="utf-8"
    )
    return DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)


def _row(app, name):
    return str(app.query_one("#code-projects", DataTable).get_row(name)[0])


async def test_running_profile_shows_run_icon_and_stopped_shows_none(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, WAIT_FOR_INPUT)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        table = app.query_one("#code-projects", DataTable)
        table.focus()
        await pilot.pause()
        assert _row(app, "alpha") == "alpha" and _row(app, "beta") == "beta"

        await pilot.press("f5")
        await until(pilot, lambda: _row(app, "alpha") == "▶ alpha")
        assert _row(app, "beta") == "beta"

        await pilot.click("#code-stop")
        await until(pilot, lambda: _row(app, "alpha") == "alpha")


async def test_icon_clears_when_an_unselected_profile_exits_on_its_own(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, EXIT_SOON)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        table = app.query_one("#code-projects", DataTable)
        table.focus()
        await pilot.press("f5")
        await until(pilot, lambda: _row(app, "alpha") == "▶ alpha")
        table.move_cursor(row=1)
        await pilot.pause()
        await until(pilot, lambda: _row(app, "alpha") == "alpha")


async def test_debugging_profile_shows_debug_icon(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, SLEEP)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        app.query_one("#code-projects", DataTable).focus()
        await pilot.press("shift+f5")
        await until(pilot, lambda: _row(app, "alpha") == "◉ alpha")
        await pilot.click("#code-stop")
        await until(pilot, lambda: _row(app, "alpha") == "alpha")
