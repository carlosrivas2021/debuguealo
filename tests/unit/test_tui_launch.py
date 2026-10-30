import pytest
from test_tui_file_picker import InspectService
from test_tui_grouping import Docker, until
from textual.widgets import Button

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


@pytest.mark.parametrize("entry", ["button", "shortcut"])
async def test_open_launch_works_without_any_running_containers(tmp_path, monkeypatch, entry):
    service, docker = InspectService(), Docker()
    docker.inventory = []
    opened = []
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    monkeypatch.setattr("debugpilot.tui.launch_file.open_launch_file", opened.append)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        if entry == "button":
            app.query_one("#open-launch-file", Button).press()
        else:
            await pilot.press("ctrl+n")
        await until(pilot, lambda: bool(opened))
        assert opened == [tmp_path / ".debugpilot" / "launch.json"]
        assert not service.inspections and not service.runs
