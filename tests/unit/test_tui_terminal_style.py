import pytest
from test_tui_grouping import Docker
from textual.widgets import Button

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


@pytest.mark.parametrize("size", [(120, 40), (80, 24)])
async def test_shell_layout_keeps_profile_actions_compact_and_focus_visible(size, tmp_path):
    config = tmp_path / ".debugpilot" / "launch.json"
    config.parent.mkdir()
    config.write_text(
        '{"version": 1, "configurations": '
        '[{"name": "Demo", "type": "docker-compose", "projectName": "demo"}]}'
    )
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=Docker()),
        workspace=tmp_path,
        refresh_interval=0.05,
    )
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        actions = app.query_one("#profile-actions")
        actions.display = True
        await pilot.pause(0.01)
        buttons = app.query("#profile-actions Button")

        assert str(actions.styles.layout) == "<horizontal>"
        assert actions.region.height == 1
        assert len(buttons) == 2
        assert all(button.region.height == 1 for button in buttons)
        assert all(button.region.width > 0 for button in buttons)
        assert all(button.region.right <= app.size.width for button in buttons)

        open_button = app.query_one("#open-launch-file", Button)
        open_button.focus()
        await pilot.pause()
        assert open_button.has_focus
        assert open_button.styles.background != app.screen.styles.background
