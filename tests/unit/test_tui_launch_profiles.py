import json
import os

from test_tui_compose import Service
from test_tui_grouping import Docker, item, select_key, until
from textual.app import App
from textual.widgets import Button, Select, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.storage.launch_profiles import LaunchProfile, LaunchProfileStore
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.compose_dialog import ComposeDialog
from debugpilot.tui.launch_save import SaveLaunchDialog


def discovered(tmp_path):
    base = tmp_path / "local" / "agents" / "docker-compose.yaml"
    override = tmp_path / "scratchpad" / "agents.ports.yaml"
    base.parent.mkdir(parents=True)
    override.parent.mkdir()
    base.write_text("name: orders\nservices: {}")
    override.write_text("services: {}")
    labels = {
        "com.docker.compose.project": "orders",
        "com.docker.compose.project.working_dir": str(base.parent),
        "com.docker.compose.project.config_files": f"{base},{override}",
    }
    docker = Docker()
    docker.inventory = [
        item("orders-api", "orders", "api").model_copy(update={"labels": labels}),
        item("orders-worker", "orders", "worker").model_copy(update={"labels": labels}),
    ]
    return docker, base, override


async def test_manual_start_registers_once_and_shortcuts_use_nested_files(tmp_path, monkeypatch):
    docker, base, override = discovered(tmp_path)
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    path = tmp_path / ".debugpilot" / "launch.json"
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_profiles) == 1)
        assert not path.parent.exists()
        assert not service.runs and not service.previews
        docker.inventory = [c.model_copy(update={"id": c.id + "-new"}) for c in docker.inventory]
        await until(pilot, lambda: "orders-api-new" in app._inventory)
        assert not path.parent.exists()
        select_key(app, "project:orders")
        await pilot.press("R")
        await until(pilot, lambda: bool(service.previews))
        project, action, target = service.previews[0]
        assert project.files == (base, override)
        assert project.project_directory == base.parent
        assert action == "rebuild" and target is None
        assert not service.runs
        await pilot.press("enter")
        await until(pilot, lambda: bool(service.runs))


async def test_pending_profile_does_not_block_logs_or_execute_actions(tmp_path, monkeypatch):
    docker, _base, _override = discovered(tmp_path)
    docker.inventory = [
        c.model_copy(update={"labels": {"com.docker.compose.project": "orders"}})
        for c in docker.inventory
    ]
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    path = tmp_path / ".debugpilot" / "launch.json"
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_profiles) == 1)
        assert not path.parent.exists()
        await until(pilot, lambda: bool(docker.opened))
        assert "pending" in str(app.query_one("#launch-state", Static).render()).lower()
        await pilot.press("r")
        assert not service.previews and not service.runs


async def test_named_profiles_select_without_overwriting_custom_fields(tmp_path, monkeypatch):
    docker, base, override = discovered(tmp_path)
    path = tmp_path / ".debugpilot" / "launch.json"
    path.parent.mkdir()
    profiles = [
        {
            "name": name,
            "type": "docker-compose",
            "projectName": "orders",
            "cwd": "${workspaceFolder}",
            "files": [str(base), str(override)],
            "up": {"build": build, "detach": True, "forceRecreate": build},
            "custom": {"keep": True},
        }
        for name, build in (("Local", False), ("Rebuild", True))
    ]
    original = json.dumps({"version": 1, "configurations": profiles}).encode()
    path.write_bytes(original)
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        select_key(app, "project:orders")
        await pilot.press("ctrl+o")
        await until(pilot, lambda: isinstance(app.screen, ComposeDialog))
        selector = app.screen.query_one("#compose-profile", Select)
        selector.value = "Rebuild"
        await until(pilot, lambda: app.screen._profile_project is not None)
        await pilot.pause()
        assert await pilot.click("#compose-preview")
        await pilot.pause()
        assert service.previews, str(app.screen.query_one("#compose-status", Static).render())
        assert service.previews[-1][0].up.build is True
        assert path.read_bytes() == original


async def test_explicit_save_creates_launch_without_running_compose(tmp_path, monkeypatch):
    docker, _base, _override = discovered(tmp_path)
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    path = tmp_path / ".debugpilot" / "launch.json"
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_profiles) == 1)
        select_key(app, "project:orders")
        await pilot.press("ctrl+o")
        await until(pilot, lambda: isinstance(app.screen, ComposeDialog))
        await pilot.pause()
        button = app.screen.query_one("#compose-save-profile", Button)
        button.press()
        await pilot.pause()
        app.screen.query_one("#launch-save-confirm", Button).press()
        await until(pilot, path.exists)
        assert len(json.loads(path.read_bytes())["configurations"]) == 1
        assert not service.previews and not service.runs
        assert list(path.parent.iterdir()) == [path]


async def test_existing_launch_save_offers_copy_without_overwriting(tmp_path, monkeypatch):
    from debugpilot.storage.launch_profiles import LaunchProfileStore
    from debugpilot.tui.launch_save import SaveLaunchDialog

    docker, _base, _override = discovered(tmp_path)
    path = tmp_path / ".debugpilot" / "launch.json"
    path.parent.mkdir()
    original = b'{"version":1,"configurations":[],"custom":"keep"}'
    path.write_bytes(original)
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path)
    copied = []
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(
            SaveLaunchDialog(LaunchProfileStore(tmp_path), {"name": "New", "projectName": "orders"})
        )
        await pilot.pause()
        assert app.screen.query_one("#launch-save-confirm", Button).disabled
        app.screen.query_one("#launch-save-copy", Button).press()
        await pilot.pause()
        assert json.loads(copied[0])["name"] == "New"
        assert "configurations" not in json.loads(copied[0])
        assert path.read_bytes() == original
        assert list(path.parent.iterdir()) == [path]


async def test_raced_editor_file_copy_exports_configuration_object(tmp_path, monkeypatch):
    store = LaunchProfileStore(tmp_path)
    raw = {"name": "Detected", "projectName": "demo", "type": "docker-compose"}
    editor_bytes = b'{"version":1,"configurations":[],"custom":"editor"}'
    real_link = os.link

    def race(source, destination):
        store.path.write_bytes(editor_bytes)
        return real_link(source, destination)

    monkeypatch.setattr("debugpilot.storage.launch_profiles.os.link", race)
    app = App()
    copied = []
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(SaveLaunchDialog(store, raw))
        await pilot.pause()
        app.screen.query_one("#launch-save-confirm", Button).press()
        await pilot.pause()
        assert store.path.read_bytes() == editor_bytes
        assert list(store.path.parent.iterdir()) == [store.path]
        app.screen.query_one("#launch-save-copy", Button).press()
        await pilot.pause()
        exported = json.loads(copied[0])
        assert exported.get("projectName") == "demo" and "configurations" not in exported, (
            "After editor creation race Copy must export an insertable configuration object"
        )


async def test_copy_saved_nested_cwd_preserves_profile_semantics(tmp_path, monkeypatch):
    docker, _, _ = discovered(tmp_path)
    process = tmp_path / "process"
    process.mkdir()
    (process / "compose.yaml").write_text("services: {}")
    store = LaunchProfileStore(tmp_path)
    raw = {
        "name": "Nested",
        "type": "docker-compose",
        "projectName": "orders",
        "cwd": "${workspaceFolder}/process",
        "files": ["compose.yaml"],
        "up": {"build": True},
        "custom": "keep",
    }
    store.save_configuration(raw)
    original = store.path.read_bytes()
    initial = store.resolve(store.profiles()[0])
    compose = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _: compose)
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    copied = []
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        select_key(app, "project:orders")
        await pilot.press("ctrl+o")
        await until(
            pilot,
            lambda: (
                isinstance(app.screen, ComposeDialog) and app.screen._selected_launch is not None
            ),
        )
        app.screen.query_one("#compose-save-profile", Button).press()
        await until(pilot, lambda: isinstance(app.screen, SaveLaunchDialog))
        app.screen.query_one("#launch-save-copy", Button).press()
        await pilot.pause()
        exported = json.loads(copied[0])
        resolved = store.resolve(LaunchProfile("Nested", "orders", None, exported))
        assert not compose.previews and not compose.runs
        assert store.path.read_bytes() == original
        assert resolved is not None and resolved.cwd == initial.cwd, (
            f"Copy changed process cwd: expected {initial.cwd}, got {resolved}"
        )
        assert resolved.files == initial.files
        assert resolved.project_directory == initial.project_directory
        assert resolved.up == initial.up
        assert exported["custom"] == "keep"
