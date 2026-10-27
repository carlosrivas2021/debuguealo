from test_tui_grouping import Docker, item, until
from textual.widgets import Checkbox, DataTable, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


def keys(app, selector):
    return [row.key.value for row in app.query_one(selector, DataTable).ordered_rows]


async def test_default_active_only_and_show_all_uses_separate_stopped_area():
    docker = Docker()
    docker.inventory = [
        item("on", "demo", "api"),
        item("off", "demo", "worker", "exited"),
        item("paused", "other", "api", "paused"),
    ]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(keys(app, "#containers")))
        assert "container:on" in keys(app, "#containers")
        assert "container:paused" in keys(app, "#containers")
        assert "container:off" not in keys(app, "#containers")
        assert not app.query_one("#stopped-area").display
        assert not app.query_one("#show-all", Checkbox).value
        await pilot.click("#show-all")
        await until(pilot, lambda: "stopped:container:off" in keys(app, "#stopped-containers"))
        assert "container:off" not in keys(app, "#containers")
        assert app.query_one("#stopped-area").display
        assert "stopped" in str(app.query_one("#stopped-title", Static).render()).lower()


async def test_hiding_selected_stopped_container_clears_selection_and_keeps_scope_safe():
    docker = Docker()
    docker.inventory = [item("on", "demo", "api"), item("off", "demo", "worker", "exited")]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(80, 24)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        await pilot.click("#show-all")
        await until(pilot, lambda: len(keys(app, "#stopped-containers")) == 2)
        table = app.query_one("#stopped-containers", DataTable)
        table.focus()
        table.move_cursor(row=1)
        await until(
            pilot, lambda: app.selected_container is not None and app.selected_container.id == "off"
        )
        assert app.selected_project == "demo"
        await pilot.click("#show-all")
        await until(pilot, lambda: app.selected_container is None)
        assert app.selected_project == "demo"
        assert not app.query_one("#stopped-area").display
        assert app.query_one("#log-entries").region.height > 0
    assert len(docker.closed) == len(docker.opened)


async def test_state_change_moves_service_between_areas_without_losing_identity():
    docker = Docker()
    docker.inventory = [item("api", "demo", "api")]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        await pilot.click("#show-all")
        docker.inventory = [item("api", "demo", "api", "exited")]
        await until(pilot, lambda: "stopped:container:api" in keys(app, "#stopped-containers"))
        assert app.selected_container.id == "api"
        assert app.selected_container.state == "exited"
        assert "container:api" not in keys(app, "#containers")
