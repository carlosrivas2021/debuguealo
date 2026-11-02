import json

from test_tui_compose import Service
from test_tui_grouping import Docker, item, select_key, until

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.storage.launch_profiles import LaunchProfileStore
from debugpilot.tui.app import DebugPilotApp


def test_central_profile_root_reaches_preview_and_confirmation(tmp_path, monkeypatch):
    settings = tmp_path / "settings"
    project_root = tmp_path / "external"
    compose = project_root / "local" / "agente" / "docker-compose.yaml"
    compose.parent.mkdir(parents=True)
    compose.write_text("services: {}\n")
    monkeypatch.setattr(
        "debugpilot.storage.launch_profiles.config_path",
        lambda: settings / "config.toml",
    )
    store = LaunchProfileStore()
    store.path.parent.mkdir(parents=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "configurations": [
                    {
                        "name": "Agente",
                        "type": "docker-compose",
                        "projectName": "local-agente",
                        "workspaceFolder": str(project_root),
                        "cwd": "${workspaceFolder}",
                        "files": ["local/agente/docker-compose.yaml"],
                    }
                ],
            }
        )
    )
    docker = Docker()
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)

    async def exercise():
        async with app.run_test(size=(120, 40)) as pilot:
            await until(pilot, lambda: len(app._launch_profiles) == 1)
            select_key(app, "profile:Agente")
            await pilot.click("#profile-recreate")
            await until(pilot, lambda: bool(service.previews))
            project, _action, _target = service.previews[-1]
            assert project.workspace == project_root.resolve()
            assert project.files == (compose.resolve(),)
            await pilot.press("enter")
            await until(pilot, lambda: bool(service.runs))
            assert service.runs[-1][0].project.workspace == project_root.resolve()

    import asyncio

    asyncio.run(exercise())
    assert not (settings / "config.toml").exists()


def test_invalid_central_roots_are_pending_without_hiding_valid_profiles(tmp_path, monkeypatch):
    root = tmp_path / "valid"
    root.mkdir()
    compose = root / "compose.yaml"
    compose.write_text("services: {}\\n")
    missing = tmp_path / "missing"
    link = tmp_path / "link"
    try:
        link.symlink_to(root, target_is_directory=True)
    except (OSError, NotImplementedError):
        link = None
    monkeypatch.setattr(
        "debugpilot.storage.launch_profiles.config_path",
        lambda: tmp_path / "settings" / "config.toml",
    )
    store = LaunchProfileStore()
    valid = {
        "type": "docker-compose",
        "projectName": "good",
        "workspaceFolder": str(root),
        "cwd": "${workspaceFolder}",
        "files": ["compose.yaml"],
    }
    invalid = [
        {
            "type": "docker-compose",
            "projectName": "missing",
            "workspaceFolder": str(missing),
            "cwd": "${workspaceFolder}",
            "files": ["compose.yaml"],
        }
    ]
    if link is not None:
        invalid.append(
            {
                "type": "docker-compose",
                "projectName": "linked",
                "workspaceFolder": str(link),
                "cwd": "${workspaceFolder}",
                "files": ["compose.yaml"],
            }
        )
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps({"version": 1, "configurations": [valid, *invalid]}))
    profiles = store.profiles()
    assert profiles[0].pending_reason is None
    assert store.resolve(profiles[0]) is not None
    for profile in profiles[1:]:
        assert profile.pending_reason == "Compose paths or launch options need attention."
        assert store.resolve(profile) is None


def test_central_inventory_stays_ephemeral_and_does_not_trust_external_labels(
    tmp_path, monkeypatch
):
    root = tmp_path / "project"
    root.mkdir()
    compose = root / "compose.yaml"
    compose.write_text("services: {}\\n")
    monkeypatch.setattr(
        "debugpilot.storage.launch_profiles.config_path",
        lambda: tmp_path / "settings" / "config.toml",
    )
    store = LaunchProfileStore()
    saved = {
        "name": "Saved",
        "type": "docker-compose",
        "projectName": "saved",
        "workspaceFolder": str(root),
        "cwd": "${workspaceFolder}",
        "files": ["compose.yaml"],
    }
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps({"version": 1, "configurations": [saved]}))
    unsafe = item("external", "untrusted", "api").model_copy(
        update={
            "labels": {
                "com.docker.compose.project": "untrusted",
                "com.docker.compose.project.working_dir": str(root),
                "com.docker.compose.project.config_files": str(compose),
            }
        }
    )
    assert store.register([unsafe])
    profiles = store.profiles()
    assert [profile.project_name for profile in profiles] == ["saved", "untrusted"]
    assert profiles[0].pending_reason is None and store.resolve(profiles[0]) is not None
    assert profiles[1].pending_reason
    assert store.resolve(profiles[1]) is None
    assert json.loads(store.path.read_text())["configurations"] == [saved]


async def test_default_app_startup_is_read_only_and_open_uses_central_path(tmp_path, monkeypatch):
    settings = tmp_path / "settings"
    monkeypatch.setattr(
        "debugpilot.storage.launch_profiles.config_path",
        lambda: settings / "config.toml",
    )
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()))
    opened = []
    monkeypatch.setattr(app, "_edit_launch_in_terminal", lambda _editor, path: opened.append(path))
    central = settings / "launch.json"
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert not central.exists()
        assert not settings.exists()
        app.action_open_launch_file()
        await until(pilot, lambda: bool(opened))
        assert opened == [central]
        assert central.exists()
        assert json.loads(central.read_text()) == {"version": 1, "configurations": []}


def test_editor_failure_still_resumes_textual_before_reraising():
    from contextlib import contextmanager
    from pathlib import Path

    import pytest

    from debugpilot.core.exceptions import ConfigurationError
    from debugpilot.tui.app import DebugPilotApp

    events = []

    @contextmanager
    def textual_like_suspend():
        # Mirrors Textual 6.x: no try/finally around the yield.
        events.append("suspend")
        yield
        events.append("resume")

    app = object.__new__(DebugPilotApp)
    app.suspend = textual_like_suspend

    def failing_editor(_path):
        raise ConfigurationError("Invalid JSON in launch.json at line 28, column 3.")

    with pytest.raises(ConfigurationError, match="Invalid JSON"):
        app._edit_launch_in_terminal(failing_editor, Path("launch.json"))
    assert events == ["suspend", "resume"]
