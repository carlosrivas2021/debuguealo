"""Ctrl+T toggles between the Containers and Code areas."""

from test_code_project_store import configure
from test_tui_grouping import Docker, ready, until

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.code_workspace import CodeWorkspace


async def test_ctrl_t_toggles_areas_and_focuses_each_area_table(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        await pilot.press("ctrl+t")
        await until(pilot, lambda: app.query_one(CodeWorkspace).display)
        assert not app.query_one("#container-area").display
        assert app.focused.id == "code-projects"
        await pilot.press("ctrl+t")
        await until(pilot, lambda: app.query_one("#container-area").display)
        assert not app.query_one(CodeWorkspace).display
        assert app.focused.id == "launch-profiles"
        assert docker.opened == []  # Switching areas never starts processes or logs.
