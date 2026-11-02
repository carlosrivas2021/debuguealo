from datetime import UTC, datetime

from test_tui_grouping import Docker, item, until
from textual.coordinate import Coordinate
from textual.widgets import RichLog

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import ContainerInfo, PortMapping
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.log_viewer import LogViewer


async def test_compose_output_is_docked_separate_and_o_restores_control(tmp_path):
    docker = Docker()
    docker.inventory = [item("demo-api", "demo", "api")]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(100, 32)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        assert app.query_one("#compose-console")
        assert not app.query_one("#profile-actions").display
        assert app.query_one("#compose-output-viewer", RichLog) is not app.query_one(LogViewer)
        assert app.query_one("#compose-output-toggle").display
        await pilot.press("o")
        await pilot.pause()
        assert not app.query_one("#compose-output-viewer").display
        assert app.query_one("#compose-output-toggle").display
        assert "show" in str(app.query_one("#compose-output-toggle").render()).lower()
        await pilot.press("o")
        await pilot.pause()
        assert app.query_one("#compose-output-viewer").display


async def test_native_inventory_scales_scrolls_and_shows_only_published_port_labels():
    docker = Docker()
    docker.inventory = [
        ContainerInfo(
            id=f"id-{index}",
            name=f"tree-service-{index}",
            image="example:latest",
            state="running",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            compose_project="tree",
            compose_service=f"service-{index}",
            ports=(
                PortMapping(
                    private_port=8000,
                    host_ip="::1" if index == 0 else "0.0.0.0",
                    public_port=9000 + index,
                ),
                PortMapping(private_port=53, protocol="udp", public_port=None),
            ),
        )
        for index in range(30)
    ]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(100, 32)) as pilot:
        await until(pilot, lambda: app._inventory_loaded and len(app._rows) >= 30)
        table = app.query_one("#launch-profiles")
        assert table.row_count == 31
        first_ports = str(table.get_cell_at(Coordinate(1, 1)))
        second_ports = str(table.get_cell_at(Coordinate(2, 1)))
        assert "[::1]:9000->8000/tcp" in first_ports
        assert "9001->8000/tcp" in second_ports
        assert "53/udp" not in first_ports
        assert table.max_scroll_y > 0
        table.scroll_end(animate=False)
        await pilot.pause()
        assert table.scroll_y > 0
