import json

from test_code_project_store import configure
from test_tui_grouping import Docker, until
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


async def test_area_navigation_keeps_container_context_and_isolates_code_errors(
    tmp_path, monkeypatch
):
    store = configure(monkeypatch, tmp_path)
    store.path.write_text("{", encoding="utf-8")
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path)
    opened = []
    monkeypatch.setattr(app, "_edit_launch_in_terminal", lambda editor, path: opened.append(path))
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        table = app.query_one("#launch-profiles", DataTable)
        cursor = table.cursor_row
        selected = app.selected_container
        await pilot.click("#area-code")
        assert app.query_one("#code-workspace").display
        assert not app.query_one("#container-area").display
        assert "Invalid code launch" in str(app.query_one("#code-status").render())
        await pilot.press("s", "r", "shift+r", "h", "c")
        assert not app.query_one("#inline-compose").display
        assert not app.query_one("#compose-console").display
        store.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "configurations": [
                        {
                            "name": "Example",
                            "workspaceFolder": str(tmp_path),
                            "command": ["npm", "run", "dev"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        await pilot.click("#code-reload")
        code_table = app.query_one("#code-projects", DataTable)
        assert code_table.row_count == 1
        assert code_table.get_row("Example") == [
            "Example",
            str(tmp_path.resolve()),
            "['npm', 'run', 'dev']",
        ]
        await pilot.press("ctrl+o")
        await until(pilot, lambda: bool(opened))
        assert opened == [store.path]
        await pilot.click("#area-containers")
        assert app.query_one("#container-area").display
        assert not app.query_one("#code-workspace").display
        assert table.cursor_row == cursor
        assert app.selected_container == selected
        await pilot.click("#area-code")
        assert code_table.get_row("Example")[0] == "Example"
