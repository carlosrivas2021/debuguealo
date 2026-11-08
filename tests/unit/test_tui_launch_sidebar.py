import json

import pytest
from test_tui_compose import Service
from test_tui_grouping import Docker, item, ready, request_logs, until
from textual.widgets import Button, DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


def write_profiles(workspace, profiles):
    path = workspace / ".debugpilot" / "launch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "configurations": profiles}))
    return path


def profile(name, project, file):
    return {
        "name": name,
        "type": "docker-compose",
        "projectName": project,
        "cwd": "${workspaceFolder}",
        "files": [str(file)],
    }


def select_profile(app, key):
    table = app.query_one("#launch-profiles", DataTable)
    table.focus()
    table.move_cursor(
        row=next(index for index, row in enumerate(table.ordered_rows) if row.key.value == key)
    )
    app._select_focused_row(table)


async def test_primary_rows_are_saved_profiles_and_link_by_project_labels(tmp_path):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {api: {}, worker: {}}\n")
    path = write_profiles(
        tmp_path,
        [
            profile("Local catalog", "catalog", compose),
            profile("Catalog staging", "catalog", compose),
        ],
    )
    docker = Docker()
    docker.inventory = [
        item("catalog-api", "catalog", "api"),
        item("catalog-worker", "catalog", "worker"),
        item("unconfigured-api", "other", "api"),
    ]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_profiles) == 2 and bool(app._inventory))
        launch_keys = [
            row.key.value for row in app.query_one("#launch-profiles", DataTable).ordered_rows
        ]
        assert launch_keys == [
            "profile:Local catalog",
            "profile-child:profile:Local catalog:catalog-api",
            "profile-child:profile:Local catalog:catalog-worker",
            "profile:Catalog staging",
            "profile-child:profile:Catalog staging:catalog-api",
            "profile-child:profile:Catalog staging:catalog-worker",
            "project:other",
            "container:unconfigured-api",
        ]
        assert not any(profile.dynamic for profile in app._launch_profiles)
        assert app.query_one("#launch-profiles", DataTable).row_count > 0
        assert (
            "projects / containers" in str(app.query_one("#launch-title").render()).lower()
        )
        assert path.exists()
        await until(pilot, lambda: ready(app))
        await request_logs(pilot, app)
        await until(pilot, lambda: len(docker.opened) >= 2)
        assert set(docker.opened) == {"catalog-api", "catalog-worker"}
        select_profile(app, "profile:Catalog staging")
        await until(pilot, lambda: app._selected_profile_name == "Catalog staging")
        assert app.selected_project == "catalog"
        assert app._selection_key == "profile:Catalog staging"


async def test_profiles_own_selectable_children_and_raw_inventory_shows_only_unowned(tmp_path):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {api: {}, worker: {}}\\n")
    write_profiles(
        tmp_path,
        [
            profile("Local catalog", "catalog", compose),
            profile("Catalog staging", "catalog", compose),
        ],
    )
    docker = Docker()
    docker.inventory = [
        item("catalog-api", "catalog", "api"),
        item("catalog-worker", "catalog", "worker", "exited"),
        item("unconfigured-api", "other", "api"),
    ]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_profiles) == 2 and bool(app._inventory))
        table = app.query_one("#launch-profiles", DataTable)
        profile_keys = [
            row.key.value for row in table.ordered_rows if row.key.value.startswith("profile:")
        ]
        assert len(profile_keys) == 2
        child_keys = [
            row.key.value for row in table.ordered_rows
            if row.key.value.startswith("profile-child:")
        ]
        assert len(child_keys) == 2
        assert len(set(child_keys)) == 2
        assert [
            row.key.value for row in table.ordered_rows
            if not row.key.value.startswith(("profile:", "profile-child:"))
        ] == ["project:other", "container:unconfigured-api"]
        assert "unconfigured-api" in str(table.get_row("container:unconfigured-api"))
        table.focus()
        table.move_cursor(
            row=next(
                i for i, row in enumerate(table.ordered_rows) if row.key.value == child_keys[0]
            )
        )
        await until(pilot, lambda: app.selected_container is not None)
        assert app.selected_container.id in {"catalog-api", "catalog-worker"}
        assert app.selected_project == "catalog"
        await request_logs(pilot, app)
        await until(pilot, lambda: len(docker.opened) >= 1)
        assert len(docker.opened) >= 1
        await pilot.click("#show-all")
        await pilot.pause(0.1)
        assert (
            sum(
                row.key.value.startswith("profile-child:")
                for row in app.query_one("#launch-profiles", DataTable).ordered_rows
            )
            == 4
        )
        assert not any(row.key.value.startswith("stopped:") for row in table.ordered_rows)
        assert len(app.query_one("#sidebar").query(DataTable)) == 1


async def test_profile_child_selection_survives_recreated_container_identity(tmp_path):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {api: {}}\n")
    write_profiles(tmp_path, [profile("Catalog", "catalog", compose)])
    docker = Docker()
    docker.inventory = [item("catalog-api-old", "catalog", "api")]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_child_rows) == 1)
        child_key = next(iter(app._launch_child_rows))
        select_profile(app, child_key)
        await until(pilot, lambda: app.selected_container is not None)
        docker.inventory = [item("catalog-api-new", "catalog", "api")]
        await until(
            pilot,
            lambda: (
                app.selected_container is not None
                and app.selected_container.id == "catalog-api-new"
            ),
        )
        assert app._selected_profile_name == "Catalog"
        assert app._selection_key == next(iter(app._launch_child_rows))


async def test_recreate_and_build_actions_work_without_running_containers(tmp_path, monkeypatch):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {api: {}}\n")
    write_profiles(tmp_path, [profile("Zero containers", "empty-project", compose)])
    docker = Docker()
    docker.inventory = []
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    monkeypatch.setattr(app, "_refresh_compose_logs", lambda *_args: _no_logs())
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles))
        assert app.query_one("#empty-welcome").display is False
        assert app.query_one("#profile-recreate", Button).label == "Play / Recreate"
        await pilot.press("r")
        await until(pilot, lambda: bool(service.previews))
        assert service.previews[-1][1:] == ("recreate", None)
        assert not service.runs
        await pilot.press("enter")
        await until(pilot, lambda: bool(service.runs))
        assert service.runs[-1][1] is True
        service.previews.clear()
        service.runs.clear()
        app.query_one("#profile-build-recreate", Button).press()
        await until(pilot, lambda: bool(service.previews))
        assert service.previews[-1][1:] == ("rebuild", None)
        await pilot.press("enter")
        await until(pilot, lambda: bool(service.runs))
        assert service.runs[-1][1] is True
        assert not any(binding.action == "restart_selected" for binding in app.BINDINGS)


async def _no_logs(*_args):
    return None


async def test_duplicate_display_names_keep_distinct_profile_rows(tmp_path):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}")
    write_profiles(
        tmp_path, [profile("Local", "first", compose), profile("Local", "second", compose)]
    )
    docker = Docker()
    docker.inventory = []
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_rows) == 2)
        table = app.query_one("#launch-profiles", DataTable)
        assert table.row_count == 2
        keys = [row.key.value for row in table.ordered_rows]
        assert keys[0] != keys[1]
        select_profile(app, keys[1])
        await until(pilot, lambda: app.selected_project == "second")


@pytest.mark.parametrize("display_name", ["Local", ""])
async def test_reordering_duplicate_names_preserves_selected_project_and_preview(
    tmp_path, monkeypatch, display_name
):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}")
    profiles = [profile(display_name, "first", compose), profile(display_name, "second", compose)]
    path = write_profiles(tmp_path, profiles)
    docker = Docker()
    docker.inventory = [item("first-api", "first", "api"), item("second-api", "second", "api")]
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_rows) == 2)
        selected_key = next(
            key for key, value in app._launch_rows.items() if value.project_name == "second"
        )
        select_profile(app, selected_key)
        await until(pilot, lambda: app.selected_project == "second")
        await pilot.press("r")
        await until(pilot, lambda: app._inline_plan is not None)
        assert app._inline_plan.project.project_name == "second"
        path.write_text(json.dumps({"version": 1, "configurations": list(reversed(profiles))}))
        await pilot.pause(0.2)
        assert app._selection_key == selected_key
        assert app.selected_project == "second"
        assert app._inline_plan is not None
        assert app._inline_plan.project.project_name == "second"
        assert not service.runs
        await pilot.press("enter")
        await until(pilot, lambda: bool(service.runs))
        assert len(service.runs) == 1
        assert service.runs[0][0].project.project_name == "second"


async def test_launch_file_change_invalidates_pinned_confirmation(tmp_path, monkeypatch):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n")
    path = write_profiles(tmp_path, [profile("Catalog", "catalog", compose)])
    docker = Docker()
    docker.inventory = []
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    monkeypatch.setattr(app, "_refresh_compose_logs", lambda *_args: _no_logs())
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles))
        await pilot.press("r")
        await until(pilot, lambda: app._inline_plan is not None)
        profiles = json.loads(path.read_text())["configurations"]
        profiles[0]["custom"] = {"saved externally": True}
        path.write_text(json.dumps({"version": 1, "configurations": profiles}))
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert not service.runs
        assert app._inline_plan is None


async def test_profiles_reload_while_docker_is_unavailable_and_raw_container_cannot_launch(
    tmp_path, monkeypatch
):
    class Offline(Docker):
        async def list_containers(self):
            raise RuntimeError("offline")

    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n")
    docker = Offline()
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: "unavailable" in str(app.query_one("#docker-state").render()))
        write_profiles(tmp_path, [profile("Offline saved", "saved-project", compose)])
        await until(pilot, lambda: len(app._launch_profiles) == 1)
        assert app._launch_profiles[0].name == "Offline saved"
        assert app.query_one("#empty-welcome").display is False
        assert "unavailable" in str(app.query_one("#docker-state").render()).lower()
        app.selected_container = item("raw", "unsaved", "api")
        app.selected_project = "unsaved"
        app._selected_profile = None
        app._selected_profile_key = None
        app._selected_profile_name = None
        app.action_recreate_selected()
        assert not service.previews


async def test_cancel_unexecuted_preview_preserves_profile_and_log_selection(tmp_path, monkeypatch):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}")
    write_profiles(tmp_path, [profile("My orders", "orders", compose)])
    docker = Docker()
    docker.inventory = [item("catalog-api", "catalog", "api"), item("orders-api", "orders", "api")]
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _: service)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_profile(app, "profile:My orders")
        await until(pilot, lambda: app._selection_key == "profile:My orders")
        await pilot.press("r")
        await until(pilot, lambda: app._inline_plan is not None)
        await pilot.press("escape")
        await pilot.pause(0.15)
        assert not service.runs
        assert not app.query_one("#inline-compose").display
        assert app._selection_key == "profile:My orders", (
            f"Cancelled preview switched to {app._selection_key}"
        )
        assert app.selected_project == "orders"
