import json
import threading
from contextlib import contextmanager

from test_tui_grouping import Docker, item, request_logs, until
from textual.widgets import DataTable, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.storage.launch_profiles import LaunchProfileStore
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.container_details import ContainerDetails


async def test_empty_launch_sidebar_opens_launch_file_directly_on_user_action(
    tmp_path, monkeypatch
):
    docker = Docker()
    docker.inventory = [item("unconfigured-api", "manual", "api")]
    opened = []
    caller_thread = threading.get_ident()
    path = tmp_path / ".debugpilot" / "launch.json"

    def ensure(_store):
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"version": 1, "configurations": []}))
        return path

    terminal_owned = []

    @contextmanager
    def suspend():
        terminal_owned.append(True)
        try:
            yield
        finally:
            terminal_owned.pop()

    def open_file(target):
        assert terminal_owned == [True]
        opened.append((target, threading.get_ident()))
        target.write_text(json.dumps({
            "version": 1,
            "configurations": [{"name": "Edited", "type": "docker-compose"}],
        }))

    monkeypatch.setattr(LaunchProfileStore, "ensure_launch_file", ensure)
    monkeypatch.setattr("debugpilot.tui.launch_file.open_launch_file", open_file)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    monkeypatch.setattr(app, "suspend", suspend)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        assert not app.query_one("#empty-welcome").display
        assert "Docker: connected" in str(app.query_one("#docker-state", Static).render())
        assert app.query_one("#launch-profiles", DataTable).row_count > 0
        # The selected container shows its details by default; logs open on request.
        await until(pilot, lambda: app.selected_container is not None)
        assert app.query_one(ContainerDetails).display
        assert not app.query_one("#logs-panel").display
        assert not path.exists()
        assert await pilot.click("#open-launch-file")
        await until(pilot, lambda: bool(opened))
        assert opened == [(path, opened[0][1])]
        assert opened[0][1] == caller_thread
        assert terminal_owned == []
        assert [
            row.key.value for row in app.query_one("#launch-profiles", DataTable).ordered_rows
            if row.key.value.startswith("profile:")
        ] == ["profile:Edited"]
        assert not app.query_one("#empty-welcome").display
        await request_logs(pilot, app)
        await until(pilot, lambda: "unconfigured-api" in docker.opened)
        assert "unconfigured-api" in docker.opened


async def test_saved_profile_welcome_is_hidden_but_docker_errors_remain_distinct(tmp_path):
    class Offline(Docker):
        async def list_containers(self):
            raise RuntimeError("offline")

    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=Offline()), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: "unavailable" in str(app.query_one("#docker-state").render()))
        assert app.query_one("#empty-welcome").display
        assert (
            "saved launch profiles"
            in str(app.query_one("#empty-welcome-message", Static).render()).lower()
        )
        assert "unavailable" in str(app.query_one("#docker-state").render()).lower()
        assert app.query_one("#logs-panel").display
