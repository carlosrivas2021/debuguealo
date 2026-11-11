"""R reloads the Code profiles, like the Reload button, without taking typed letters."""

import json
import sys

from test_code_project_store import configure
from test_tui_grouping import Docker, until
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp

ECHO_INPUT = "print('READY', flush=True); print('GOT:' + input(), flush=True)"


def _write(store, tmp_path, names):
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "configurations": [
                    {
                        "name": name,
                        "workspaceFolder": str(tmp_path),
                        "command": [sys.executable, "-u", "-c", ECHO_INPUT],
                    }
                    for name in names
                ],
            }
        ),
        encoding="utf-8",
    )


def _app(monkeypatch, tmp_path):
    store = configure(monkeypatch, tmp_path)
    _write(store, tmp_path, ["first"])
    return DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path), store


async def test_r_reloads_code_profiles_and_shows_in_the_footer(monkeypatch, tmp_path):
    app, store = _app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        table = app.query_one("#code-projects", DataTable)
        table.focus()
        await pilot.pause()
        assert table.row_count == 1
        shown = {
            key: active.binding.description
            for key, active in app.screen.active_bindings.items()
            if active.binding.show and active.enabled
        }
        assert shown.get("r") == "Reload"

        _write(store, tmp_path, ["first", "second"])
        await pilot.press("r")
        await until(pilot, lambda: table.row_count == 2)
        # Recreate belongs to Containers; R in Code never opens a Compose preview.
        assert not app.query_one("#inline-compose").display


async def test_r_typed_into_a_live_terminal_reaches_the_program(monkeypatch, tmp_path):
    app, store = _app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        table = app.query_one("#code-projects", DataTable)
        table.focus()
        await pilot.press("f5")
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: "READY" in pane.render().plain)

        _write(store, tmp_path, ["first", "second"])
        pane.focus()
        await pilot.press("r", "enter")
        await until(pilot, lambda: "GOT:r" in pane.render().plain)
        assert table.row_count == 1
