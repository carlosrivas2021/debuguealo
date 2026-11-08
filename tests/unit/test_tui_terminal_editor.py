from contextlib import contextmanager

from test_tui_grouping import Docker, until
from textual.widgets import Button

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.container_details import ContainerDetails


async def test_editor_failure_restores_terminal_and_allows_retry(tmp_path, monkeypatch):
    ownership = []
    attempts = []
    notices = []

    @contextmanager
    def suspend():
        ownership.append(True)
        try:
            yield
        finally:
            ownership.pop()

    def editor(path):
        assert ownership == [True]
        attempts.append(path)
        raise ConfigurationError("Install nano or vi on PATH")

    monkeypatch.setattr("debugpilot.tui.launch_file.open_launch_file", editor)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path, refresh_interval=0.05
    )
    monkeypatch.setattr(app, "suspend", suspend)
    monkeypatch.setattr(app, "notify", lambda message, **_kwargs: notices.append(message))
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        for count in (1, 2):
            app.query_one("#open-launch-file", Button).press()
            await until(
                pilot, lambda count=count: len(attempts) == count and app._launch_open_task is None
            )
            assert ownership == []
            assert notices[-1] == "Cannot open launch.json: Install nano or vi on PATH"
        assert attempts == [tmp_path / ".debugpilot" / "launch.json"] * 2
        # The dashboard is restored: the selected container shows its details by default.
        assert app.selected_container is not None
        assert app.query_one(ContainerDetails).display
        assert not app.query_one("#logs-panel").display
