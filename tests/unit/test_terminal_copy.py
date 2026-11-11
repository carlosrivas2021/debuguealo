"""Ctrl+C copies a selection from a live terminal; without one it still interrupts."""

import json
import sys

from test_code_project_store import configure
from test_tui_grouping import Docker, until
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp

LONG_RUNNING = "import time; print('HELLO COPY WORLD', flush=True); time.sleep(60)"


def _app(monkeypatch, tmp_path):
    store = configure(monkeypatch, tmp_path)
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "configurations": [
                    {
                        "name": "service",
                        "workspaceFolder": str(tmp_path),
                        "command": [sys.executable, "-u", "-c", LONG_RUNNING],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)


async def _select_first_word(pilot, pane):
    content, region = pane.content_region, pane.region
    x, y = content.x - region.x, content.y - region.y
    await pilot.mouse_down("#code-terminal", offset=(x, y))
    await pilot.hover("#code-terminal", offset=(x + 5, y))
    await pilot.mouse_up("#code-terminal", offset=(x + 5, y))
    await pilot.pause()


async def test_ctrl_c_copies_the_selection_and_keeps_the_process_running(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    copied = []
    app.copy_to_clipboard = copied.append
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        app.query_one("#code-projects", DataTable).focus()
        await pilot.press("f5")
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: "HELLO COPY WORLD" in pane.render().plain)

        await _select_first_word(pilot, pane)
        await pilot.press("ctrl+c")
        await pilot.pause(0.5)

        assert copied == ["HELLO"]
        assert pane.active
        assert not app.screen.selections

        await pilot.press("ctrl+c")
        await until(pilot, lambda: not pane.active)
        assert copied == ["HELLO"]
