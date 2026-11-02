import json

import pytest
from test_tui_grouping import Docker, item, select_key, until
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
        table = app.query_one("#launch-profiles", DataTable)
        key = "stopped:container:orders-worker"
        await until(pilot, lambda: key in table.rows)
        table.focus()
        table.move_cursor(row=table.get_row_index(key))
        await pilot.pause()
        await pilot.press("s", "enter")
        assert not docker.stops


async def test_saved_profile_status_distinguishes_inactive_active_and_pending(tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    (tmp_path / "standby.yaml").write_text("services: {}\n")
    profile_file = tmp_path / ".debugpilot" / "launch.json"
    profile_file.parent.mkdir(parents=True)
    profile_file.write_text(
        json.dumps(
            {
                "version": 1,
                "configurations": [
                    {
                        "name": "Orders",
                        "type": "docker-compose",
                        "projectName": "orders",
                        "cwd": "${workspaceFolder}",
                        "files": ["compose.yaml"],
                    },
                    {
                        "name": "Standby",
                        "type": "docker-compose",
                        "projectName": "standby",
                        "cwd": "${workspaceFolder}",
                        "files": ["standby.yaml"],
                    },
                    {
                        "name": "Pending",
                        "type": "docker-compose",
                        "projectName": "pending",
                        "cwd": "${workspaceFolder}",
                        "files": ["missing.yaml"],
                    },
                ],
            }
        )
    )
    docker = StopDocker()
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_profiles) == 3 and bool(docker.opened))
        table = app.query_one("#launch-profiles", DataTable)
        statuses = {
            row.key.value: table.get_row_at(index)[2]
            for index, row in enumerate(table.ordered_rows)
            if row.key.value.startswith("profile:")
        }
        assert statuses["profile:Orders"] == "2 active"
        assert statuses["profile:Standby"] == "Stop"
        assert statuses["profile:Pending"] == "Pending"


@pytest.mark.parametrize("cancel_first", [False, True])
async def test_saved_profile_parent_stop_pins_active_project_members(tmp_path, cancel_first):
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    profile_file = tmp_path / ".debugpilot" / "launch.json"
    profile_file.parent.mkdir(parents=True)
    profile_file.write_text(
        json.dumps(
            {
                "version": 1,
                "configurations": [
                    {
                        "name": "Orders",
                        "type": "docker-compose",
                        "projectName": "orders",
                        "cwd": "${workspaceFolder}",
                        "files": ["compose.yaml"],
                    }
                ],
            }
        )
    )
    docker = StopDocker()
    docker.inventory = [
        item("orders-api", "orders", "api"),
        item("orders-worker", "orders", "worker"),
        item("orders-inactive", "orders", "inactive", "exited"),
        item("other-api", "other", "api"),
        item("standalone"),
    ]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles) and bool(docker.opened))
        select_key(app, "profile:Orders")
        await until(pilot, lambda: app._selection_key == "profile:Orders")
        await pilot.press("s")
        assert app.query_one("#inline-compose").display
        message = str(app.query_one("#inline-compose-message", Static).render())
        assert "orders" in message and "2 active container(s)" in message
        targets = str(app.query_one("#inline-compose").tooltip)
        assert "orders-api" in targets and "orders-worker" in targets
        assert "orders-inactive" not in targets and "other-api" not in targets
        if cancel_first:
            await pilot.press("escape")
            assert not docker.stops
            assert not app.query_one("#inline-compose").display
            await pilot.press("s")
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(docker.stops))
        assert docker.stops == [(("orders-api", "orders-worker"), True, 10)]
        await until(pilot, lambda: app._inline_task.done())
        assert app._selection_key == "profile:Orders"
        assert app.query_one("#launch-profiles", DataTable).has_focus
