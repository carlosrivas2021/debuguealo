"""Independent S6/S7 T18 public action-target regressions; fake boundaries only."""
import hashlib
import json

from test_tui_compose import Service
from test_tui_grouping import Docker, item, until
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import StopResult
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


def workspace(root):
    compose = root / "compose.yaml"
    compose.write_text("services: {api: {}, worker: {}}\n")
    launch = root / ".debugpilot" / "launch.json"
    launch.parent.mkdir()
    launch.write_text(json.dumps({"version": 1, "configurations": [
        {"name": name, "type": "docker-compose", "projectName": "demo",
         "cwd": "${workspaceFolder}", "files": ["compose.yaml"],
         "up": {"build": build, "detach": detach, "forceRecreate": force}}
        for name, build, detach, force in (
            ("Local", False, True, False), ("Rebuild", True, False, True))
    ]}))
    originals = {path: path.read_bytes() for path in (compose, launch)}
    return originals


def unchanged(originals):
    for path, original in originals.items():
        assert path.read_bytes() == original
        assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(original).digest()


class TargetsDocker(Docker):
    def __init__(self):
        super().__init__()
        self.inventory = [item("actual-api-17", "demo", "api"),
                          item("actual-worker-29", "demo", "worker"),
                          item("other-41", "other", "api")]
        self.stops = []

    async def stop_containers(self, targets, *, confirmed=False, timeout_seconds=10):
        self.stops.append((tuple(targets), confirmed, timeout_seconds))
        return StopResult(stopped=targets, failed={})


async def choose(app, pilot, key):
    table = app.query_one("#launch-profiles", DataTable)
    table.focus()
    table.move_cursor(row=table.get_row_index(key))
    await until(pilot, lambda: app._selection_key == key and table.has_focus)


def fake_terminal(app):
    opened = []

    async def open_terminal(kind, **context):
        opened.append((kind, context))

    app._open_terminal = open_terminal
    return opened


async def test_stop_confirmation_is_pinned_but_exec_uses_changed_current_target(tmp_path):
    originals = workspace(tmp_path)
    docker = TargetsDocker()
    endpoint = "unix:///var/run/docker.sock"
    app = DebugPilotApp(DebugPilotEngine(Settings(docker_endpoint=endpoint), docker=docker),
                        workspace=tmp_path, refresh_interval=0.05)
    opened = fake_terminal(app)
    async with app.run_test(size=(140, 50)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        assert not opened and not docker.stops
        await choose(app, pilot, "profile-child:profile:Local:actual-api-17")
        await pilot.press("s")
        assert app.query_one("#inline-compose").display and not docker.stops
        unchanged(originals)
        await choose(app, pilot, "profile-child:profile:Local:actual-worker-29")
        assert not opened
        await pilot.press("c")
        await until(pilot, lambda: len(opened) == 1)
        kind, context = opened[0]
        assert kind == "container"
        assert context == {"target": docker.inventory[1], "endpoint": endpoint, "cwd": tmp_path}
        assert app.selected_container.id == "actual-worker-29"
        assert not docker.stops
        unchanged(originals)
        # Confirmation belongs to the original preview, never to the new cursor.
        assert await pilot.click("#inline-compose-confirm")
        # Stops run in the background; wait for this one to finish.
        await until(pilot, lambda: bool(docker.stops) and not app._stopping)
        assert docker.stops == [(("actual-api-17",), True, 10)]
        unchanged(originals)
        await choose(app, pilot, "profile-child:profile:Local:actual-worker-29")
        await pilot.press("s")
        assert app.query_one("#inline-compose").display
        assert await pilot.click("#inline-compose-cancel")
        assert not app.query_one("#inline-compose").display
        assert docker.stops == [(("actual-api-17",), True, 10)] and len(opened) == 1
        unchanged(originals)
    unchanged(originals)


async def test_recreate_same_project_profiles_keep_options_and_reject_stale_profile(
    tmp_path, monkeypatch
):
    originals = workspace(tmp_path)
    docker, service = TargetsDocker(), Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker),
                        workspace=tmp_path, refresh_interval=0.05)
    opened = fake_terminal(app)
    async with app.run_test(size=(140, 50)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        assert not opened and not service.previews and not service.runs
        await choose(app, pilot, "profile-child:profile:Rebuild:actual-api-17")
        await pilot.press("r")
        assert app.query_one("#inline-compose").display and not service.runs
        assert service.previews[-1][0].up.build is True
        await choose(app, pilot, "profile-child:profile:Local:actual-worker-29")
        assert not app.query_one("#inline-compose").display
        await pilot.press("enter")  # stale preview is no longer confirmable
        assert not service.runs and not opened and not docker.stops
        unchanged(originals)
        for name, identity, options in (
            ("Local", "actual-worker-29", (False, True, False)),
            ("Rebuild", "actual-api-17", (True, False, True)),
        ):
            await choose(app, pilot, f"profile-child:profile:{name}:{identity}")
            assert app.selected_container.id == identity
            assert app.selected_container.compose_service == (
                "worker" if name == "Local" else "api")
            await pilot.press("r")
            project, action, scope = service.previews[-1]
            assert action == "recreate" and project.project_name == "demo"
            # The public profile action deliberately recreates ALL services.
            assert scope is None
            assert (project.up.build, project.up.detach, project.up.force_recreate) == options
            assert project.files == ((tmp_path / "compose.yaml").resolve(),)
            previous = len(service.runs)
            unchanged(originals)
            assert await pilot.click("#inline-compose-confirm")
            await until(
                pilot, lambda: "demo" in app._compose_tasks and app._compose_tasks["demo"].done()
            )
            assert len(service.runs) == previous + 1
            plan, confirmed = service.runs[-1]
            assert confirmed is True and plan.project == project and plan.service is None
            assert app.selected_container.id == identity and app._selected_profile_name == name
            assert not opened and not docker.stops
            unchanged(originals)
        assert len(service.runs) == 2
    unchanged(originals)
