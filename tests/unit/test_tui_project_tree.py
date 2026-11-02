"""Fresh, bounded checks for the selected project's real inventory hierarchy."""

import json

from test_tui_compose import Service
from test_tui_grouping import Docker, item, until
from textual.widgets import Checkbox, DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import PortMapping
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


def profile_workspace(root):
    (root / "compose.yaml").write_text("services: {}\n")
    path = root / ".debugpilot" / "launch.json"
    path.parent.mkdir()
    original = json.dumps(
        {
            "version": 1,
            "configurations": [
                {
                    "name": name,
                    "type": "docker-compose",
                    "projectName": "demo",
                    "cwd": "${workspaceFolder}",
                    "files": ["compose.yaml"],
                    "up": {"build": build},
                }
                for name, build in (("Local", False), ("Rebuild", True))
            ],
        }
    ).encode()
    path.write_bytes(original)
    return path, original


def row_text(table, key, column):
    return str(table.get_row(key)[column])


def assert_profile_file_unchanged(path, original):
    assert path.read_bytes() == original


async def test_profile_children_show_real_ports_and_keep_named_profile_identity(tmp_path):
    path, original = profile_workspace(tmp_path)
    docker = Docker()
    docker.inventory = [
        item("demo-api", "demo", "api").model_copy(
            update={
                "ports": (PortMapping(private_port=8080, public_port=443, host_ip="::1"),)
            }
        ),
        item("loose"),
    ]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: "profile-child:profile:Rebuild:demo-api" in table.rows)
        assert [str(column.label) for column in table.columns.values()] == [
            "Project / container", "Published ports", "State"
        ]
        assert [
            row.key.value for row in table.ordered_rows if row.key.value.startswith("profile")
        ] == [
            "profile:Local", "profile-child:profile:Local:demo-api",
            "profile:Rebuild", "profile-child:profile:Rebuild:demo-api",
        ]
        for name in ("Local", "Rebuild"):
            assert name in row_text(table, f"profile:{name}", 0)
            assert "demo" in row_text(table, f"profile:{name}", 0)
            assert row_text(table, f"profile-child:profile:{name}:demo-api", 1) == (
                "[::1]:443->8080/tcp"
            )
        table.focus()
        table.move_cursor(row=2)
        await until(pilot, lambda: app._selected_profile_name == "Rebuild")
        assert app.selected_project == "demo" and app.selected_container is None
        await pilot.press("down")
        await until(pilot, lambda: app.selected_container is not None)
        assert app.selected_container.id == "demo-api"
        assert app._selected_profile_name == "Rebuild"
        assert_profile_file_unchanged(path, original)
    assert_profile_file_unchanged(path, original)


async def test_one_tree_collapses_filters_and_preserves_action_targets(tmp_path, monkeypatch):
    path, original = profile_workspace(tmp_path)
    docker = Docker()
    docker.inventory = [
        item("demo-api", "demo", "api"),
        item("demo-worker", "demo", "worker", state="exited"),
        item("loose"),
        item("idle", state="exited"),
    ]
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    opened, stopped = [], []

    async def open_terminal(kind, **context):
        opened.append((kind, context))

    async def stop_containers(targets, *, confirmed=False):
        stopped.append((tuple(target.id for target in targets), confirmed))

    app._open_terminal = open_terminal
    app.engine.stop_containers = stop_containers
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        assert len(app.query_one("#sidebar").query(DataTable)) == 1
        table = app.query_one("#launch-profiles", DataTable)
        assert [row.key.value for row in table.ordered_rows] == [
            "profile:Local", "profile-child:profile:Local:demo-api",
            "profile:Rebuild", "profile-child:profile:Rebuild:demo-api",
            "standalone:", "container:loose",
        ]
        assert not opened and not stopped and not service.runs
        app.query_one("#show-all", Checkbox).toggle()
        await until(pilot, lambda: table.row_count == 9)
        table.focus()
        table.move_cursor(row=0)
        await pilot.press("space")
        await until(pilot, lambda: table.row_count == 7)
        assert "profile-child:profile:Local:demo-api" not in table.rows
        assert app.selected_container is None and app._selected_profile_name == "Local"
        await pilot.press("space")
        await until(pilot, lambda: table.row_count == 9)
        table.move_cursor(row=table.get_row_index("container:loose"))
        await until(pilot, lambda: app.selected_container is not None)
        assert app.selected_container.id == "loose" and app._selected_profile_name is None
        await pilot.press("c", "h")
        await until(pilot, lambda: len(opened) == 2)
        assert opened[0][0] == "container" and opened[0][1]["target"].id == "loose"
        assert opened[0][1]["cwd"] == tmp_path and opened[0][1]["endpoint"]
        assert opened[1] == ("host", {"cwd": tmp_path})
        await pilot.press("s")
        await until(pilot, lambda: app.query_one("#inline-compose").display)
        assert app._pending_stop == ("loose",) and not stopped
        await pilot.press("escape")
        assert not stopped
        table.focus()
        table.move_cursor(row=table.get_row_index("profile:Rebuild"))
        await until(pilot, lambda: app._selected_profile_name == "Rebuild")
        await pilot.press("r")
        await until(pilot, lambda: bool(service.previews))
        project, action, target = service.previews[0]
        assert project.project_name == "demo" and project.up.build
        assert action == "recreate" and target is None and not service.runs
        await pilot.press("escape")
        assert not service.runs
        assert_profile_file_unchanged(path, original)
    assert_profile_file_unchanged(path, original)


async def test_standalone_inventory_is_visible_without_saved_profiles(tmp_path):
    docker = Docker()
    docker.inventory = [item("only")]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        assert len(app.query_one("#sidebar").query(DataTable)) == 1
        table = app.query_one("#launch-profiles", DataTable)
        assert table.display and "container:only" in table.rows
        table.focus()
        table.move_cursor(row=table.get_row_index("container:only"))
        await until(pilot, lambda: app.selected_container is not None)
        assert app.selected_container.id == "only"
