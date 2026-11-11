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


COUNT_STARTS = (
    "from pathlib import Path\n"
    "marker = Path('starts.txt')\n"
    "marker.write_text(marker.read_text() + 'x' if marker.exists() else 'x')\n"
    "import time\n"
    "print('READY', flush=True)\n"
    "time.sleep(60)\n"
)


def _counting_app(monkeypatch, tmp_path):
    store = configure(monkeypatch, tmp_path)
    (tmp_path / "main.py").write_text(COUNT_STARTS, encoding="utf-8")
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "configurations": [
                    {
                        "name": "service",
                        "workspaceFolder": str(tmp_path),
                        "command": [sys.executable, "-u", "main.py"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    return app, tmp_path / "starts.txt"


def _footer(app):
    return {
        key: active.binding.description
        for key, active in app.screen.active_bindings.items()
        if active.binding.show and active.enabled
    }


async def test_r_restarts_a_running_profile(monkeypatch, tmp_path):
    app, starts = _counting_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        app.query_one("#code-projects", DataTable).focus()
        await pilot.press("f5")
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: starts.exists() and starts.read_text() == "x")
        await until(pilot, lambda: _footer(app).get("r") == "Restart")

        await pilot.press("r")
        await until(pilot, lambda: starts.read_text() == "xx")
        await until(pilot, lambda: "READY" in pane.render().plain and pane.active)
        assert "Running" in str(app.query_one("#code-run-state").render())

        await pilot.click("#code-stop")
        await until(pilot, lambda: _footer(app).get("r") == "Reload")


async def test_r_restarts_a_debug_session_in_debug_mode(monkeypatch, tmp_path):
    app, starts = _counting_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        app.query_one("#code-projects", DataTable).focus()
        await pilot.press("shift+f5")
        await until(pilot, lambda: starts.exists() and starts.read_text() == "x")
        await until(pilot, lambda: _footer(app).get("r") == "Restart")

        await pilot.press("r")
        await until(pilot, lambda: starts.read_text() == "xx")
        await until(pilot, lambda: _footer(app).get("r") == "Restart")
        # Still a debug session, not a plain run.
        assert app.query_one("#code-debug-output").display
        assert not app.query_one("#code-terminal").contexts.get("service")

        await pilot.click("#code-stop")
        await until(pilot, lambda: _footer(app).get("r") == "Reload")
