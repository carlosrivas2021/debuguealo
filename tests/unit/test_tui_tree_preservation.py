"""Integrated preservation of a mixed tree after viewport and width repairs."""

import json

import pytest
from test_tui_grouping import item, until
from test_tui_inventory_scroll import ControlledInventory
from test_tui_inventory_width import assert_columns_fit
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import PortMapping
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


@pytest.mark.asyncio
async def test_mixed_tree_retains_viewport_targets_and_live_ports_across_resize(tmp_path):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n")
    launch = tmp_path / ".debugpilot" / "launch.json"
    launch.parent.mkdir()
    launch.write_text(json.dumps({"version": 1, "configurations": [{
        "name": "Local", "type": "docker-compose", "projectName": "demo",
        "cwd": "${workspaceFolder}", "files": ["compose.yaml"],
    }]}))
    original = (compose.read_bytes(), launch.read_bytes())
    docker = ControlledInventory()
    docker.inventory[0] = docker.inventory[0].model_copy(update={
        "ports": (PortMapping(private_port=8080, public_port=18080),),
    })
    docker.inventory.append(item("external-proxy", "external", "proxy").model_copy(update={
        "ports": (PortMapping(private_port=9000, public_port=19000),),
    }))
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: docker.requested == 2 and table.row_count == 43)
        owned = "profile-child:profile:Local:api-00"
        external = "container:external-proxy"
        keys = {row.key.value for row in table.ordered_rows}
        assert {"profile:Local", owned, "project:external", external} <= keys
        sidebar = app.query_one("#sidebar")
        assert len(sidebar.query(DataTable)) == 1
        assert sidebar.scrollbar_gutter.right == sidebar.styles.scrollbar_size_vertical
        table.focus()
        table.move_cursor(row=table.get_row_index(owned))
        await until(pilot, lambda: app.selected_container is not None)
        assert app.selected_container.id == "api-00" and app.selected_project == "demo"
        await pilot.pause()
        assert_columns_fit(table)
        assert table.max_scroll_y > 0
        table.scroll_end(animate=False)
        await pilot.pause()
        viewport = table.scroll_y
        assert viewport > 0
        docker.allow_refresh.put_nowait(None)
        await until(pilot, lambda: docker.returned == 2)
        await pilot.pause()
        assert table.scroll_y == viewport
        assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == owned
        for width, height in [(80, 24), (90, 28), (120, 40)]:
            await pilot.resize_terminal(width, height)
            await pilot.pause()
            assert sidebar.scrollbar_gutter.right == sidebar.styles.scrollbar_size_vertical
            assert_columns_fit(table)
            assert {row.key.value for row in table.ordered_rows} == keys
            assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == owned
            assert app.selected_container.id == "api-00" and app.selected_project == "demo"
        table.move_cursor(row=table.get_row_index(external))
        await until(pilot, lambda: (
            app.selected_container is not None and app.selected_container.id == "external-proxy"
        ))
        assert app.selected_project == "external"
        assert "18080->8080/tcp" in str(table.get_row(owned)[1])
        assert "19000->9000/tcp" in str(table.get_row(external)[1])
        for index, private, public in [(0, 8080, 28080), (-1, 9000, 29000)]:
            docker.inventory[index] = docker.inventory[index].model_copy(update={
                "ports": (PortMapping(private_port=private, public_port=public),),
            })
        docker.allow_refresh.put_nowait(None)
        await until(pilot, lambda: docker.returned == 3)
        await until(pilot, lambda: "28080->8080/tcp" in str(table.get_row(owned)[1]))
        await until(pilot, lambda: "29000->9000/tcp" in str(table.get_row(external)[1]))
        await pilot.pause()
        assert_columns_fit(table)
        assert {row.key.value for row in table.ordered_rows} == keys
        assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == external
        assert app.selected_container.id == "external-proxy" and app.selected_project == "external"
        assert (compose.read_bytes(), launch.read_bytes()) == original
