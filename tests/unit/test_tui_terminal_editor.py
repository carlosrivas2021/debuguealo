"""A launch.json that cannot be opened is reported, and Ctrl+O can be retried."""

from test_tui_grouping import Docker, until
from textual.widgets import Button

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage import text_files
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.container_details import ContainerDetails
from debugpilot.tui.file_editor import FileEditorScreen


async def test_open_failure_is_reported_and_a_retry_opens_the_editor(tmp_path, monkeypatch):
    attempts = []
    notices = []
    real_load = text_files.load_text

    def load(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise ConfigurationError(f"{path} is not UTF-8 text.")
        return real_load(path)

    monkeypatch.setattr(text_files, "load_text", load)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path, refresh_interval=0.05
    )
    monkeypatch.setattr(app, "notify", lambda message, **_kwargs: notices.append(message))
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        launch = tmp_path / ".debugpilot" / "launch.json"

        app.query_one("#open-launch-file", Button).press()
        await until(pilot, lambda: len(attempts) == 1 and app._launch_open_task is None)
        assert notices[-1] == f"Cannot open launch.json: {launch} is not UTF-8 text."
        assert not isinstance(app.screen, FileEditorScreen)
        # The dashboard is untouched: the selected container shows its details by default.
        await until(
            pilot,
            lambda: app.selected_container is not None and app.query_one(ContainerDetails).display,
        )

        app.query_one("#open-launch-file", Button).press()
        await until(pilot, lambda: isinstance(app.screen, FileEditorScreen))
        assert attempts == [launch, launch]


async def test_dashboard_shortcuts_do_nothing_while_the_editor_is_open(tmp_path):
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        await pilot.press("ctrl+o")
        await until(pilot, lambda: isinstance(app.screen, FileEditorScreen))
        editor = app.screen

        for key in ("ctrl+o", "ctrl+t", "ctrl+l"):
            await pilot.press(key)
            await pilot.pause()
        assert app.screen is editor
        assert len([s for s in app.screen_stack if isinstance(s, FileEditorScreen)]) == 1
        assert app.query_one("#container-area").display
        assert not app.query_one("#code-workspace").display
