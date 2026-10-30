import json

import pytest
from test_tui_compose import Service
from test_tui_grouping import Docker, item, until
from textual.widgets import Checkbox, DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import StopResult
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


def write_profiles(workspace, profiles):
    path = workspace / ".debugpilot" / "launch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "configurations": profiles}))
    return path


def profile(name, project, compose):
    return {
        "name": name,
        "type": "docker-compose",
        "projectName": project,
        "cwd": "${workspaceFolder}",
        "files": [str(compose)],
    }


class StopDocker(Docker):
    def __init__(self):
        super().__init__()
        self.stops = []

    async def stop_containers(self, targets, *, confirmed=False, timeout_seconds=10):
        self.stops.append((targets, confirmed, timeout_seconds))
        return StopResult(stopped=targets, failed={})


def make_app(tmp_path, monkeypatch, *, docker=None):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n")
    path = write_profiles(tmp_path, [profile("Owned", "owned", compose)])
    docker = docker or Docker()
    docker.inventory = [
        item("a", "owned", "api"),
        item("b", "owned", "worker"),
        item("s", "owned", "old", "exited"),
        item("u", "other", "api"),
        item("t", "other", "old", "exited"),
    ]
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _: service)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker),
        workspace=tmp_path,
        refresh_interval=0.05,
    )
    return app, docker, service, path


async def navigate_to_child(app, pilot, identity="b"):
    table = app.query_one("#launch-profiles", DataTable)
    await until(pilot, lambda: bool(app._launch_child_rows))
    target = next(key for key in app._launch_child_rows if key.endswith(f":{identity}"))
    row = next(index for index, row in enumerate(table.ordered_rows) if row.key.value == target)
    table.focus()
    await pilot.pause()
    await pilot.click("#launch-profiles", offset=(5, row + 1))
    await until(
        pilot,
        lambda: table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == target,
    )
    await until(
        pilot,
        lambda: (
            app.selected_container is not None
            and app.selected_container.id == identity
            and app._selection_key == target
        ),
    )
    return target


async def test_profile_reload_reconciles_unchanged_inventory(tmp_path, monkeypatch):
    app, docker, _service, path = make_app(tmp_path, monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_child_rows))
        assert {row.container.id for row in app._rows.values() if row.container} == {"u"}
        path.write_text(json.dumps({"version": 1, "configurations": []}))
        await until(pilot, lambda: not app._launch_profiles)
        await until(
            pilot,
            lambda: (
                {row.container.id for row in app._rows.values() if row.container} == {"a", "b", "u"}
            ),
        )
        compose = tmp_path / "compose.yaml"
        path.write_text(
            json.dumps({"version": 1, "configurations": [profile("Owned", "owned", compose)]})
        )
        await until(
            pilot,
            lambda: (
                bool(app._launch_profiles)
                and {row.container.id for row in app._rows.values() if row.container} == {"u"}
            ),
        )


async def test_show_all_counts_and_displays_owned_and_unowned_stopped(tmp_path, monkeypatch):
    app, _docker, _service, _path = make_app(tmp_path, monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_child_rows))
        checkbox = app.query_one("#show-all", Checkbox)
        assert str(checkbox.label) == "Show all (2 stopped)"
        await pilot.click("#show-all")
        await until(pilot, lambda: len(app._launch_child_rows) == 3)
        assert "s" in {item.id for _, item in app._launch_child_rows.values()}
        assert "stopped:container:t" in {
            row.key.value for row in app.query_one("#stopped-containers", DataTable).ordered_rows
        }
        assert str(checkbox.label) == "Show all (2 stopped)"
        await pilot.click("#show-all")
        await until(pilot, lambda: len(app._launch_child_rows) == 2)
        assert "stopped:container:t" not in {
            row.key.value for row in app.query_one("#stopped-containers", DataTable).ordered_rows
        }


@pytest.mark.parametrize("finish", ["cancel", "run", "stop"])
async def test_child_actions_retain_child_selection_and_log_target(tmp_path, monkeypatch, finish):
    docker = StopDocker() if finish == "stop" else Docker()
    app, docker, service, _path = make_app(tmp_path, monkeypatch, docker=docker)
    async with app.run_test(size=(120, 40)) as pilot:
        child_key = await navigate_to_child(app, pilot)
        if finish == "stop":
            await pilot.press("s")
            assert app._pending_stop == ("b",)
            await pilot.click("#inline-compose-cancel")
            assert not docker.stops
        else:
            await pilot.press("r")
            await until(pilot, lambda: app._inline_plan is not None)
            assert app._inline_plan.project.project_name == "owned"
            assert app._inline_plan.service is None
            assert not service.runs
            if finish == "cancel":
                await pilot.press("escape")
            else:
                await pilot.click("#inline-compose-confirm")
                await until(pilot, lambda: app._inline_task is not None and app._inline_task.done())
        await pilot.pause(0.1)
        assert app._selection_key == child_key
        assert app.selected_container is not None and app.selected_container.id == "b"
        assert app.query_one("#launch-profiles", DataTable).has_focus
        assert "u" not in docker.opened


async def test_queued_child_cursor_synchronous_refresh_preserves_visible_selection(
    tmp_path, monkeypatch
):
    app, docker, _service, _path = make_app(tmp_path, monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_child_rows))
        table = app.query_one("#launch-profiles", DataTable)
        table.focus()
        await pilot.pause()
        target = next(key for key in app._launch_child_rows if key.endswith(":b"))
        row = next(
            index for index, value in enumerate(table.ordered_rows) if value.key.value == target
        )
        with table.prevent(DataTable.RowHighlighted):
            table.move_cursor(row=row)
        app._update_launch_profiles(docker.inventory)
        assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == target
        assert app.selected_container is not None and app.selected_container.id == "b"


@pytest.mark.parametrize("trigger", ["refresh", "resize"])
async def test_queued_child_cursor_survives_refresh_and_resize(tmp_path, monkeypatch, trigger):
    app, docker, _service, _path = make_app(tmp_path, monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_child_rows))
        table = app.query_one("#launch-profiles", DataTable)
        table.focus()
        target = next(key for key in app._launch_child_rows if key.endswith(":b"))
        row = next(
            index for index, value in enumerate(table.ordered_rows) if value.key.value == target
        )
        with table.prevent(DataTable.RowHighlighted):
            await pilot.click("#launch-profiles", offset=(5, row + 1))
        assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == target
        if trigger == "refresh":
            docker.inventory = [*docker.inventory, item("new", "other", "worker")]
            await until(pilot, lambda: "new" in app._inventory)
        else:
            app._resize_inventory()
        await until(pilot, lambda: app._selection_key == target)
        assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == target
        assert app.selected_container is not None and app.selected_container.id == "b"
