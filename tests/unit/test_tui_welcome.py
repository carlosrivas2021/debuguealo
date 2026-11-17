import json

from test_tui_grouping import Docker, item, request_logs, until
from textual.widgets import DataTable, Static, TextArea

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.storage.launch_profiles import LaunchProfileStore
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.container_details import ContainerDetails
from debugpilot.tui.file_editor import FileEditorScreen


async def test_empty_launch_sidebar_opens_launch_file_directly_on_user_action(
    tmp_path, monkeypatch
):
    docker = Docker()
    docker.inventory = [item("unconfigured-api", "manual", "api")]
    path = tmp_path / ".debugpilot" / "launch.json"

    def ensure(_store):
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"version": 1, "configurations": []}))
        return path

    monkeypatch.setattr(LaunchProfileStore, "ensure_launch_file", ensure)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
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
        # Ready once its editor is mounted, not merely pushed.
        await until(pilot, lambda: isinstance(app.screen, FileEditorScreen)
                    and app.screen.query(TextArea))
        assert [file.loaded.path for file in app.screen.files] == [path.resolve()]

        app.screen.query_one(TextArea).text = json.dumps({
            "version": 1,
            "configurations": [{"name": "Edited", "type": "docker-compose"}],
        })
        await pilot.press("ctrl+s")
        await pilot.press("escape")
        await until(pilot, lambda: not isinstance(app.screen, FileEditorScreen))
        await until(pilot, lambda: [
            row.key.value for row in app.query_one("#launch-profiles", DataTable).ordered_rows
            if row.key.value.startswith("profile:")
        ] == ["profile:Edited"])
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
