"""Public Code UI behavior for non-owning Go attach sessions."""

import asyncio
import json

import pytest
from test_code_debug_ui import debug_app, rendered, until

from debugpilot.tui import code_debug


class FakeGoAttach:
    instances = []

    def __init__(self, on_event, on_output):
        self.on_event = on_event
        self.on_output = on_output
        self.events = asyncio.Queue()
        self.state = "idle"
        self.verified_breakpoints = {}
        self.requested_breakpoints = {}
        self.exit_code = None
        self.closed = False
        self.instances.append(self)

    def emit(self, name, **body):
        message = {"event": name, "body": body}
        self.events.put_nowait(message)
        self.on_event(message)

    async def start(self, profile, breakpoints):
        self.profile = profile
        self.requested_breakpoints = dict(breakpoints)
        self.state = "running"
        self.emit("state", state="running")

    async def close(self):
        self.closed = True
        self.state = "closed"

    async def stack(self):
        return []

    async def set_breakpoints(self, source, lines):
        return []


@pytest.fixture
async def attach_app(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    profile = config["configurations"][0]
    profile.pop("command", None)
    profile["goAttach"] = {"host": "127.0.0.1", "port": 2345, "remoteRoot": "/app"}
    store.path.write_text(json.dumps(config), encoding="utf-8")
    FakeGoAttach.instances = []
    monkeypatch.setattr(code_debug, "GoAttachSession", FakeGoAttach, raising=False)
    return app, roots, store


async def test_attach_dispatch_snapshots_profile_and_disconnect_is_nonowning(attach_app):
    app, roots, _ = attach_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("shift+f5")
        await until(pilot, lambda: bool(FakeGoAttach.instances))
        session = FakeGoAttach.instances[0]
        assert session.profile.go_attach.host == "127.0.0.1"
        assert session.profile.command == ()
        assert session.profile.root == roots[0]
        assert "Attached" in rendered(app, "#code-run-state")
        assert app.query_one("#code-stop").label == "Disconnect"
        assert not app.query_one("#code-terminal").active
        await pilot.click("#code-stop")
        assert session.closed
        state = rendered(app, "#code-run-state")
        assert "Disconnected" in state
        assert "Exited" not in state


async def test_attach_only_f5_warns_without_starting_a_local_process(attach_app):
    app, _roots, _store = attach_app
    started = []
    async with app.run_test(size=(120, 45)) as pilot:
        workspace = app.query_one("#code-workspace")
        async def run(profile):
            started.append(profile)
        workspace._start = run
        await pilot.click("#area-code")
        await pilot.press("f5")
        await pilot.pause()
        assert started == []
        assert not app.query_one("#code-terminal").active
        assert "Shift+F5" in rendered(app, "#code-run-state")


async def test_attach_profile_with_command_keeps_original_f5_run_behavior(attach_app):
    app, _roots, store = attach_app
    config = json.loads(store.path.read_text(encoding="utf-8"))
    config["configurations"][0]["command"] = ["go", "run", "main.go", "literal arg"]
    store.path.write_text(json.dumps(config), encoding="utf-8")
    started = []
    async with app.run_test(size=(120, 45)) as pilot:
        async def run(profile):
            started.append(profile.command)
        app.query_one("#code-workspace")._start = run
        await pilot.click("#area-code")
        await pilot.press("f5")
        await until(pilot, lambda: bool(started))
        assert started == [("go", "run", "main.go", "literal arg")]
        assert FakeGoAttach.instances == []


async def test_attach_controls_remain_bound_to_started_profile(attach_app):
    app, roots, store = attach_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("shift+f5")
        await until(pilot, lambda: bool(FakeGoAttach.instances))
        session = FakeGoAttach.instances[0]
        config = json.loads(store.path.read_text(encoding="utf-8"))
        config["configurations"].append({
            "name": "other", "workspaceFolder": str(roots[1]), "command": ["python", "x.py"]
        })
        store.path.write_text(json.dumps(config), encoding="utf-8")
        workspace = app.query_one("#code-workspace")
        workspace.reload_profiles()
        table = app.query_one("#code-projects")
        table.move_cursor(row=1)
        await pilot.pause()
        assert app.query_one("#source-browser").root_path == roots[1].resolve()
        assert session.profile.root == roots[0]
        await pilot.click("#area-containers")
        await pilot.click("#area-code")
        assert session.profile.name == "one"
        assert app.query_one("#code-stop").disabled is False
        await pilot.click("#code-stop")
        assert session.closed
