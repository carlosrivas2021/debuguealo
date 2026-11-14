import pytest
from test_tui_file_picker import InspectService
from test_tui_grouping import Docker, until
from textual.widgets import Button

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.file_editor import FileEditorScreen


@pytest.mark.parametrize("entry", ["button", "shortcut"])
async def test_open_launch_works_without_any_running_containers(tmp_path, monkeypatch, entry):
    service, docker = InspectService(), Docker()
    docker.inventory = []
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        if entry == "button":
            app.query_one("#open-launch-file", Button).press()
        else:
            await pilot.press("ctrl+n")
            await pilot.pause()
            assert not isinstance(app.screen, FileEditorScreen)
            await pilot.press("ctrl+o")
        await until(pilot, lambda: isinstance(app.screen, FileEditorScreen))
        expected = (tmp_path / ".debugpilot" / "launch.json").resolve()
        assert [file.loaded.path for file in app.screen.files] == [expected]
        assert not service.inspections and not service.runs
