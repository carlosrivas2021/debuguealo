import pytest
from test_tui_grouping import Docker, item, ready, until
from textual.widgets import Checkbox, DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.compose_dialog import ComposeDialog


def keys(app, selector):
    return [row.key.value for row in app.query_one(selector, DataTable).ordered_rows]


async def test_default_active_only_and_show_all_uses_one_tree():
    docker = Docker()
    docker.inventory = [
        item("on", "demo", "api"),
        item("off", "demo", "worker", "exited"),
        item("paused", "other", "api", "paused"),
    ]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(keys(app, "#launch-profiles")))
        assert "container:on" in keys(app, "#launch-profiles")
        assert "container:paused" in keys(app, "#launch-profiles")
        assert "container:off" not in keys(app, "#launch-profiles")
        assert "stopped:container:off" not in keys(app, "#launch-profiles")
        assert len(app.query_one("#sidebar").query(DataTable)) == 1
        assert not app.query_one("#show-all", Checkbox).value
        await pilot.click("#show-all")
        await until(pilot, lambda: "stopped:container:off" in keys(app, "#launch-profiles"))
        assert "container:off" not in keys(app, "#launch-profiles")
        assert str(app.query_one("#show-all", Checkbox).label) == "Show all (1 stopped)"
        assert len(app.query_one("#sidebar").query(DataTable)) == 1


async def test_hiding_selected_stopped_container_clears_selection_and_keeps_scope_safe():
    docker = Docker()
    docker.inventory = [item("on", "demo", "api"), item("off", "demo", "worker", "exited")]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(80, 24)) as pilot:
        await until(pilot, lambda: ready(app))
        await pilot.click("#show-all")
        await until(pilot, lambda: "stopped:container:off" in keys(app, "#launch-profiles"))
        table = app.query_one("#launch-profiles", DataTable)
        table.focus()
        table.move_cursor(row=table.get_row_index("stopped:container:off"))
        await until(
            pilot, lambda: app.selected_container is not None and app.selected_container.id == "off"
        )
        assert app.selected_project == "demo"
        await pilot.click("#show-all")
        await until(pilot, lambda: app.selected_container is None)
        assert app.selected_project == "demo"
        assert "stopped:container:off" not in keys(app, "#launch-profiles")
        # The project selection shows its overview instead of auto-opening logs.
        assert app.query_one("#project-overview").region.height > 0
    assert len(docker.closed) == len(docker.opened)


async def test_state_change_rekeys_service_without_losing_identity():
    docker = Docker()
    docker.inventory = [item("api", "demo", "api")]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        await pilot.click("#show-all")
        docker.inventory = [item("api", "demo", "api", "exited")]
        await until(pilot, lambda: "stopped:container:api" in keys(app, "#launch-profiles"))
        assert app.selected_container.id == "api"
        assert app.selected_container.state == "exited"
        assert "container:api" not in keys(app, "#launch-profiles")


@pytest.mark.parametrize("entry", ["click", "keyboard"])
async def test_focusing_first_stopped_group_pins_the_action_target(entry):
    docker = Docker()
    docker.inventory = [item("on", "gateway", "api"), item("off", "orders", "api", "exited")]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        assert app.selected_project == "gateway"
        await pilot.click("#show-all")
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: "project:orders" in keys(app, "#launch-profiles"))
        row = table.get_row_index("project:orders")
        if entry == "click":
            await pilot.click("#launch-profiles", offset=(3, row + 1))
        else:
            for _ in range(8):
                await pilot.press("tab")
                if table.has_focus:
                    break
            table.move_cursor(row=max(0, row - 1))
            await pilot.press("down" if row else "up")
        assert table.has_focus and table.cursor_row == row
        await pilot.press("r")
        assert not isinstance(app.screen, ComposeDialog)
        assert app.selected_project == "orders"
        app._open_compose()
        await pilot.pause()
        assert isinstance(app.screen, ComposeDialog)
        assert app.screen.query_one("#compose-project").value == "orders"
        assert app.screen.query_one("#compose-scope").value == "project"
        assert app.screen.query_one("#compose-action").value == "recreate"


@pytest.mark.parametrize("size", [(120, 40), (80, 24)])
async def test_inventory_tree_fits_sidebar_without_horizontal_scroll(size):
    docker = Docker()
    project = "a-realistic-project-with-a-very-long-descriptive-name"
    docker.inventory = [
        item("container-with-a-long-name-api-1", project, "api"),
        item("container-with-a-long-name-background-worker-1", project, "worker", "exited"),
    ]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=size) as pilot:
        await until(pilot, lambda: ready(app))
        await pilot.click("#show-all")
        await pilot.pause()
        table = app.query_one("#launch-profiles", DataTable)
        assert len(app.query_one("#sidebar").query(DataTable)) == 1
        assert table.max_scroll_x == 0
        assert table.region.width > 0 and table.region.height > 0
        await pilot.resize_terminal(90, 28)
        await pilot.pause()
        assert table.max_scroll_x == 0
        assert table.region.width > 0 and table.region.height > 0
