import pytest
from test_tui_grouping import Docker, select_key, until
from textual.widgets import Checkbox, DataTable, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import StopResult
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


class StopDocker(Docker):
    def __init__(self):
        super().__init__()
        self.stops = []

    async def stop_containers(self, targets, *, confirmed=False, timeout_seconds=10):
        self.stops.append((targets, confirmed, timeout_seconds))
        self.inventory = [
            c.model_copy(update={"state": "exited"}) if c.id in targets else c
            for c in self.inventory
        ]
        return StopResult(stopped=targets, failed={})


@pytest.mark.parametrize(
    "target,expected",
    [
        ("container:orders-api", ("orders-api",)),
        ("project:orders", ("orders-api", "orders-worker")),
        ("container:standalone", ("standalone",)),
    ],
)
async def test_stop_requires_confirmation_and_pins_target_without_launch_config(target, expected):
    docker = StopDocker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        select_key(app, target)
        await pilot.press("s")
        assert not docker.stops
        assert "Stop" in str(app.query_one("#inline-compose-message", Static).render())
        select_key(app, "container:gateway-api")
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(docker.stops))
        assert docker.stops == [(expected, True, 10)]
        await until(pilot, lambda: app._inline_task.done())
        assert all(c.state == "exited" for c in docker.inventory if c.id in expected)
        assert all(c.state == "running" for c in docker.inventory if c.id not in expected)


async def test_cancel_stop_and_filter_typing_do_not_touch_docker():
    docker = StopDocker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test() as pilot:
        await until(pilot, lambda: bool(docker.opened))
        await pilot.press("s", "escape")
        assert not docker.stops
        app.query_one("#filter-logs").focus()
        await pilot.press("s")
        assert not docker.stops
        assert not app.query_one("#inline-compose").display


async def test_stopped_group_does_not_stop_its_active_siblings():
    docker = StopDocker()
    docker.inventory = [
        c.model_copy(update={"state": "exited"}) if c.id == "orders-worker" else c
        for c in docker.inventory
    ]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test() as pilot:
        await until(pilot, lambda: bool(docker.opened))
        app.query_one("#show-all", Checkbox).value = True
        await until(pilot, lambda: app.query_one("#stopped-containers", DataTable).row_count > 0)
        table = app.query_one("#stopped-containers", DataTable)
        table.focus()
        table.move_cursor(row=0)
        await pilot.pause()
        await pilot.press("s", "enter")
        assert not docker.stops
