from datetime import UTC, datetime

from test_tui_grouping import Docker, item, until
from textual.widgets import Input, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import ContainerInfo, PortMapping
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


async def test_d_opens_actual_selected_container_details_and_escape_returns_to_logs():
    docker = Docker()
    selected = ContainerInfo(
        id="actual-id",
        name="real-api-1",
        image="example/api:4",
        state="running",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        compose_project="real-project",
        compose_service="api",
        ports=(PortMapping(private_port=8080, public_port=443, host_ip="::1"),),
    )
    docker.inventory = [selected]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(100, 32)) as pilot:
        await until(pilot, lambda: app.selected_container is not None)
        app.query_one("#launch-profiles").focus()
        await pilot.press("d")
        await pilot.pause()
        details = app.query_one("#container-details")
        assert details.display
        content = str(app.query_one("#container-details-content", Static).render())
        expected_values = (
            "real-api-1",
            "example/api:4",
            "running",
            "real-project",
            "api",
            "[::1]:443->8080/tcp",
        )
        for expected in expected_values:
            assert expected in content
        await pilot.press("escape")
        await pilot.pause()
        assert not details.display
        assert app.query_one("#logs-panel").display


async def test_r_s_remain_confirmed_and_shortcuts_do_not_eat_input_text():
    docker = Docker()
    docker.inventory = [item("demo-api", "demo", "api")]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(100, 32)) as pilot:
        await until(pilot, lambda: app.selected_container is not None)
        field = app.query_one("#filter-logs", Input)
        field.focus()
        await pilot.press("r", "s")
        assert field.value.endswith("rs")
        assert not app.query_one("#inline-compose").display
        stopped = []

        async def stop_containers(targets, *, confirmed=False):
            stopped.append((targets, confirmed))

        app.engine.stop_containers = stop_containers
        app.query_one("#launch-profiles").focus()
        await pilot.press("s")
        await pilot.pause()
        assert app.query_one("#inline-compose").display
        assert app._pending_stop == ("demo-api",)
        assert not stopped
        await pilot.press("escape")
        assert not stopped
