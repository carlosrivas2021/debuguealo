import json

import pytest
from test_tui_grouping import Docker, item, ready, select_key, until
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
        await until(pilot, lambda: ready(app))
        select_key(app, target)
        await pilot.press("s")
        assert not docker.stops
        assert "Stop" in str(app.query_one("#inline-compose-message", Static).render())
        select_key(app, "container:gateway-api")
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(docker.stops))
        assert docker.stops == [(expected, True, 10)]
        await until(pilot, lambda: not app._stop_tasks and not app._stopping)
        assert all(c.state == "exited" for c in docker.inventory if c.id in expected)
        assert all(c.state == "running" for c in docker.inventory if c.id not in expected)


class SlowStopDocker(StopDocker):
    def __init__(self):
        super().__init__()
        import asyncio

        self.release = asyncio.Event()

    async def stop_containers(self, targets, *, confirmed=False, timeout_seconds=10):
        await self.release.wait()
        return await super().stop_containers(
            targets, confirmed=confirmed, timeout_seconds=timeout_seconds
        )


async def test_stop_reports_to_output_and_keeps_the_list_usable_while_waiting():
    from textual.widgets import RichLog

    docker = SlowStopDocker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:orders-api")
        await pilot.press("s")
        await until(pilot, lambda: app.query_one("#inline-compose").display)
        await pilot.click("#inline-compose-confirm")
        await pilot.pause()
        table = app.query_one("#launch-profiles", DataTable)
        # Docker has not answered yet, but the list still owns the keyboard.
        assert not docker.stops and app.focused is table
        viewer = app.query_one("#compose-output-viewer", RichLog)
        text = lambda: "\n".join(line.text for line in viewer.lines)  # noqa: E731
        assert "[Stop] Stopping orders-api" in text()
        docker.release.set()
        await until(pilot, lambda: not app._stop_tasks and not app._stopping)
        assert "[Stop] orders-api stopped." in text()


async def test_a_second_stop_can_be_sent_while_the_first_still_waits():
    from textual.widgets import RichLog

    docker = SlowStopDocker()
    pending = []
    original = docker.stop_containers

    async def tracked(targets, **kwargs):
        pending.append(targets)
        return await original(targets, **kwargs)

    docker.stop_containers = tracked
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:orders-api")
        await pilot.press("s")
        await until(pilot, lambda: app.query_one("#inline-compose").display)
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: pending == [("orders-api",)])
        # The confirmation bar is free again while Docker is still stopping orders-api.
        assert not app.query_one("#inline-compose").display
        select_key(app, "container:orders-api")
        await pilot.press("s")
        assert not app.query_one("#inline-compose").display  # already stopping
        select_key(app, "container:gateway-api")
        await pilot.press("s")
        await until(pilot, lambda: app.query_one("#inline-compose").display)
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: len(pending) == 2)
        # Stopping the whole project only targets the member not already stopping.
        select_key(app, "project:orders")
        await pilot.press("s")
        await until(pilot, lambda: app.query_one("#inline-compose").display)
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: len(pending) == 3)
        assert pending == [("orders-api",), ("gateway-api",), ("orders-worker",)]
        assert app._project_is_stopping("orders") and not app._project_is_stopping("catalog")
        docker.release.set()
        await until(pilot, lambda: len(docker.stops) == 3)
        viewer = app.query_one("#compose-output-viewer", RichLog)
        await until(pilot, lambda: sum("stopped." in line.text for line in viewer.lines) == 3)
        await until(pilot, lambda: not app._stopping)


async def test_cancel_stop_and_filter_typing_do_not_touch_docker():
    docker = StopDocker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test() as pilot:
        await until(pilot, lambda: ready(app))
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
        await until(pilot, lambda: ready(app))
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
        await until(pilot, lambda: len(app._launch_profiles) == 3 and ready(app))
        table = app.query_one("#launch-profiles", DataTable)
        statuses = {
            row.key.value: str(table.get_row_at(index)[2])
            for index, row in enumerate(table.ordered_rows)
            if row.key.value.startswith("profile:")
        }
        # Compact "active/total" counters fit the narrow State column; "…" marks setup needed.
        assert statuses["profile:Orders"] == "2/2"
        assert statuses["profile:Standby"] == "0/0"
        assert statuses["profile:Pending"] == "…"


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
        await until(pilot, lambda: bool(app._launch_profiles) and ready(app))
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
        await until(pilot, lambda: app.query_one("#inline-compose").display)
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(docker.stops))
        assert docker.stops == [(("orders-api", "orders-worker"), True, 10)]
        await until(pilot, lambda: not app._stop_tasks and not app._stopping)
        assert app._selection_key == "profile:Orders"
        assert app.query_one("#launch-profiles", DataTable).has_focus


async def test_saved_profile_with_services_stops_only_those_services(tmp_path):
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
                        "services": ["api"],
                    }
                ],
            }
        )
    )
    docker = StopDocker()
    docker.inventory = [
        item("orders-api", "orders", "api"),
        item("orders-worker", "orders", "worker"),
    ]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles) and ready(app))
        select_key(app, "profile:Orders")
        await until(pilot, lambda: app._selection_key == "profile:Orders")
        await pilot.press("s")
        message = str(app.query_one("#inline-compose-message", Static).render())
        assert "1 active container(s)" in message
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(docker.stops))
        assert docker.stops == [(("orders-api",), True, 10)]
