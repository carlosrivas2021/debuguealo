"""Production Textual visual rules; SVG frames contain labelled fixture data."""

import asyncio
import json
import os
from pathlib import Path

import pytest
from test_tui_grouping import item, request_logs, until
from test_tui_inventory_scroll import ControlledInventory
from textual.widgets import DataTable, Footer, Input, Select

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import LogEntry
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.execution_console import ExecutionConsole
from debugpilot.tui.log_viewer import LogViewer


def save_frame(app, directory, filename, title):
    Path(directory, filename).write_text(app.export_screenshot(title=title))


class FixtureSession:
    def __init__(self, **callbacks):
        self.callbacks = callbacks

    async def open_host(self, *_args):
        self.callbacks["on_output"]("Fixture shell — not a real Bash process\r\n")

    async def close_session(self):
        pass

    def resize(self, *_args):
        pass

    def write(self, _data):
        pass


class VisualInventory(ControlledInventory):
    async def stream_logs(self, name, **_options):
        yield LogEntry(timestamp="22:48:55", stream="stdout", severity="info",
                       text=f"[FIXTURE] {name}: service ready; not live Docker output")
        await asyncio.Event().wait()


@pytest.mark.parametrize("rule", ["tree", "toolbar", "terminal", "palette"])
async def test_actual_dashboard_visual_rules(tmp_path, monkeypatch, rule):
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    launch = tmp_path / ".debugpilot" / "launch.json"
    launch.parent.mkdir()
    launch.write_text(json.dumps({"version": 1, "configurations": [{
        "name": "Conversation", "type": "docker-compose", "projectName": "demo",
        "cwd": "${workspaceFolder}", "files": ["compose.yaml"],
    }]}))
    docker = VisualInventory()
    docker.inventory.append(item("mcp-tools", "MCP", "tools"))
    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", FixtureSession)
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker),
                        workspace=tmp_path, refresh_interval=0.05)
    async with app.run_test(size=(140, 44)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: docker.requested == 2 and table.row_count == 43)
        await pilot.pause()
        if rule == "tree":
            assert app.query_one("#sidebar").region.width >= 46
            assert next(iter(table.columns.values())).width >= 18
            assert "Conversation" in str(table.get_row("profile:Conversation")[0])
            assert table.max_scroll_x == 0
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            assert table.max_scroll_x == 0
        elif rule == "toolbar":
            # The log toolbar lives in the log panel, which opens on request.
            await request_logs(pilot, app)
            await pilot.pause()
            controls = [
                app.query_one(s) for s in ("#filter-logs", "#search-logs", "#severity-logs")
            ]
            assert all(control.region.height == 1 for control in controls)
            assert len({control.region.y for control in controls}) == 1
            viewer = app.query_one(LogViewer)
            viewer.append(LogEntry(text="visual preservation ready", severity="info"))
            app.query_one("#filter-logs", Input).value = "visual preservation"
            app.query_one("#severity-logs", Select).value = "info"
            viewer.flush()
            assert [entry.text for entry in viewer.visible_entries] == [
                "visual preservation ready"
            ]
        elif rule == "terminal":
            console = app.query_one(ExecutionConsole)
            host = app.query_one("#host-terminal")
            pane = host.terminal_pane
            assert not host.display
            await pilot.press("t")
            await until(pilot, lambda: pane.active)
            await pilot.pause()
            assert host.display and pane.region.height > 0
            pane._session.callbacks["on_exit"]()  # The user types `exit`.
            await until(pilot, lambda: not pane.active)
            await pilot.pause()
            assert not host.display
            assert console.region.height <= 3
        else:
            header = table.get_component_rich_style("datatable--header")
            assert header.bgcolor.get_truecolor().hex == "#101518"
            assert app.query_one(Footer).styles.background.hex.lower() == "#101518"
            artifact = os.environ.get("VISUAL_ARTIFACT_DIR")
            if artifact:
                save_frame(app, artifact, "dashboard-linux.svg",
                           "DebugPilot · Linux · FIXTURE data, not Docker")
                await pilot.resize_terminal(80, 24)
                await pilot.pause()
                save_frame(app, artifact, "dashboard-linux-compact.svg",
                           "DebugPilot · compact · FIXTURE data")
