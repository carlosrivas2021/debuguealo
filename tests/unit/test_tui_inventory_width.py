"""Real column geometry across resize and vertical-scrollbar transitions."""

import pytest
from test_tui_grouping import item, until
from test_tui_inventory_scroll import ControlledInventory
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import PortMapping
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


def assert_columns_fit(table):
    occupied = sum(column.width + 2 * table.cell_padding for column in table.columns.values())
    assert occupied <= table.scrollable_content_region.width, (
        occupied, table.scrollable_content_region.width, table.max_scroll_x
    )
    assert table.max_scroll_x == 0
    assert table.region.width > 0 and table.region.height > 0


@pytest.mark.asyncio
async def test_padded_columns_fit_through_resize_and_scrollbar_transition(tmp_path):
    docker = ControlledInventory()
    project = "project-with-a-long-descriptive-name"
    first = item("container-with-long-api-name", project, "api").model_copy(update={
        "ports": (PortMapping(private_port=8080, public_port=18080),),
    })
    docker.inventory = [first, item("container-with-long-worker-name", project, "worker")]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: docker.requested == 2 and table.row_count == 3)
        key = "container:" + first.id
        table.focus()
        table.move_cursor(row=table.get_row_index(key))
        await until(pilot, lambda: app.selected_container is not None)
        await pilot.pause()
        assert_columns_fit(table)
        assert table.max_scroll_y == 0
        assert "18080->8080/tcp" in str(table.get_row(key)[1])
        original_keys = {row.key.value for row in table.ordered_rows}
        for width, height in [(80, 24), (90, 28), (120, 40)]:
            await pilot.resize_terminal(width, height)
            await pilot.pause()
            assert_columns_fit(table)
            assert {row.key.value for row in table.ordered_rows} == original_keys
            assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == key
            assert app.selected_container.id == first.id
        docker.inventory.extend(item(f"worker-{i}", project, "worker") for i in range(35))
        docker.allow_refresh.put_nowait(None)
        await until(pilot, lambda: docker.returned == 2 and table.row_count == 38)
        await pilot.pause()
        assert table.max_scroll_y > 0
        assert_columns_fit(table)
        assert original_keys <= {row.key.value for row in table.ordered_rows}
        assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == key
        assert app.selected_container.id == first.id and app.selected_project == project
        assert "18080->8080/tcp" in str(table.get_row(key)[1])
