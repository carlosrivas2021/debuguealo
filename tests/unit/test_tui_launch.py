import pytest
from test_tui_file_picker import InspectService
from test_tui_grouping import Docker, until
from textual.widgets import Button, Select

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.compose_dialog import ComposeDialog
from debugpilot.tui.file_picker import ComposeFilePicker


@pytest.mark.parametrize("entry", ["button", "shortcut"])
async def test_open_compose_works_without_any_running_containers(monkeypatch, entry):
    service, docker = InspectService(), Docker()
    docker.inventory = []
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        if entry == "button":
            await pilot.click("#open-compose")
        else:
            await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, ComposeFilePicker))
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, ComposeDialog))
        assert app.screen.query_one("#compose-action", Select).value == "start"
        assert app.screen.query_one("#compose-scope", Select).value == "project"
        assert app.screen.query_one("#compose-confirm", Button).disabled
        assert not service.inspections and not service.runs
        await pilot.press("escape")
