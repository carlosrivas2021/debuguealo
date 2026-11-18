"""Viewport preservation through controlled, genuine inventory refreshes."""

import asyncio
import json

import pytest
from test_tui_grouping import Docker, item, until
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import PortMapping
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


class ControlledInventory(Docker):
    def __init__(self):
        super().__init__()
        self.inventory = [item(f"api-{i:02}", "demo", f"api-{i:02}") for i in range(40)]
        self.allow_refresh = asyncio.Queue()
        self.requested = 0
        self.returned = 0

    async def list_containers(self):
        self.requested += 1
        if self.requested > 1:
            await self.allow_refresh.get()
        self.returned += 1
        return list(self.inventory)


@pytest.mark.parametrize("owned", [False, True])
async def test_unchanged_refresh_keeps_viewport_and_selection_but_updates_ports(tmp_path, owned):
    if owned:
        (tmp_path / "compose.yaml").write_text("services: {}\n")
        launch = tmp_path / ".debugpilot" / "launch.json"
        launch.parent.mkdir()
        launch.write_text(json.dumps({"version": 1, "configurations": [{
            "name": "Local", "type": "docker-compose", "projectName": "demo",
            "cwd": "${workspaceFolder}", "files": ["compose.yaml"],
        }]}))
    docker = ControlledInventory()
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(100, 32)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: docker.requested == 2 and table.row_count == 41)
        key = "profile-child:profile:Local:api-00" if owned else "container:api-00"
        table.focus()
        table.move_cursor(row=table.get_row_index(key))
        await until(pilot, lambda: app.selected_container is not None)
        assert app.selected_container.id == "api-00"
        await pilot.pause()
        assert table.max_scroll_y > 0
        table.scroll_end(animate=False)
        await pilot.pause()
        viewport = table.scroll_y
        assert viewport > 0
        docker.allow_refresh.put_nowait(None)
        await until(pilot, lambda: docker.returned == 2)
        await pilot.pause()
        assert table.scroll_y == viewport
        assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == key
        assert app.selected_container.id == "api-00" and app.selected_project == "demo"
        # A viewport-preservation optimization must not cache stale published data.
        docker.inventory[0] = docker.inventory[0].model_copy(update={
            "ports": (PortMapping(private_port=8080, public_port=18080),),
        })
        docker.allow_refresh.put_nowait(None)
        await until(pilot, lambda: docker.returned == 3)
        await until(pilot, lambda: "18080->8080/tcp" in str(table.get_row(key)[1]))
        assert table.row_count == 41
        assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == key
        assert app.selected_container.id == "api-00"


async def test_refitting_the_columns_keeps_the_view_where_the_user_left_it(tmp_path):
    # The first draw can happen before the table has its real width; the refresh that
    # then refits the columns used to jump the view back to the selected row.
    docker = ControlledInventory()
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(100, 32)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: docker.requested == 2 and table.row_count == 41)
        table.focus()
        table.move_cursor(row=table.get_row_index("container:api-00"))
        await until(pilot, lambda: app.selected_container is not None)
        await pilot.pause()
        table.scroll_end(animate=False)
        await pilot.pause()
        viewport = table.scroll_y
        assert viewport > 0
        app._inventory_widths.clear()  # As if the first draw had used another width.
        app._render_launch_profiles()
        # The view is put back after the redraw's refresh.
        await until(pilot, lambda: table.scroll_y == viewport)
        assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == (
            "container:api-00")
