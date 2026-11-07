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
        self.close_entered = asyncio.Event()
        self.close_gate = None
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
        self.close_entered.set()
        if self.close_gate is not None:
            await self.close_gate.wait()
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


async def test_stop_reserves_same_profile_until_close_but_not_other_profiles(attach_app):
    app, roots, store = attach_app
    config = json.loads(store.path.read_text(encoding="utf-8"))
    config["configurations"][1]["goAttach"] = {
        "host": "127.0.0.1", "port": 2346, "remoteRoot": "/app"
    }
    store.path.write_text(json.dumps(config), encoding="utf-8")
    gate = asyncio.Event()
    stop_tasks = []
    async with app.run_test(size=(120, 45)) as pilot:
        try:
            await pilot.click("#area-code")
            await pilot.press("shift+f5")
            await until(pilot, lambda: len(FakeGoAttach.instances) == 1)
            first = FakeGoAttach.instances[0]
            first.close_gate = gate
            workspace = app.query_one("#code-workspace")
            stop_tasks.append(asyncio.create_task(workspace.stop()))
            await asyncio.wait_for(first.close_entered.wait(), 2)

            app.action_run_code()
            app.action_debug_code()
            stop_tasks.append(asyncio.create_task(workspace.stop()))
            await asyncio.sleep(0)
            repeat_joined = not stop_tasks[-1].done()
            assert len(FakeGoAttach.instances) == 1
            assert not app.query_one("#code-terminal").contexts

            table = app.query_one("#code-projects")
            table.move_cursor(row=1)
            await pilot.pause()
            app.action_debug_code()
            await until(pilot, lambda: len(FakeGoAttach.instances) == 2)
            second = FakeGoAttach.instances[1]
            await until(pilot, lambda: hasattr(second, "profile"))
            assert second.profile.go_attach.port == 2346
            assert not first.closed and not second.closed

            gate.set()
            await asyncio.gather(*stop_tasks)
            assert first.closed and not second.closed
            selected_status = rendered(app, "#code-run-state")
            selected_disconnect = app.query_one("#code-stop").label == "Disconnect"
            same_profile_restarted = False
            table.move_cursor(row=0)
            await pilot.pause()
            app.action_debug_code()
            await until(pilot, lambda: len(FakeGoAttach.instances) == 3)
            restarted = FakeGoAttach.instances[2]
            await until(pilot, lambda: hasattr(restarted, "profile"))
            same_profile_restarted = restarted is not first
            assert restarted.profile.go_attach.port == 2345
            await pilot.click("#code-stop")
            assert restarted.closed and not second.closed
            table.move_cursor(row=1)
            await pilot.pause()
            await pilot.click("#code-stop")
            assert second.closed
            assert repeat_joined and "Attached: two" in selected_status and selected_disconnect, (
                "Stop must join existing cleanup and leave the newly selected profile's "
                f"presentation intact; joined={repeat_joined}, status={selected_status!r}, "
                f"disconnect={selected_disconnect}, restarted={same_profile_restarted}"
            )
        finally:
            gate.set()
            await asyncio.gather(*stop_tasks, return_exceptions=True)


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


async def test_attach_controls_follow_selected_profile_and_stop_only_selected(attach_app):
    app, roots, store = attach_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("shift+f5")
        await until(pilot, lambda: bool(FakeGoAttach.instances))
        session = FakeGoAttach.instances[0]
        config = json.loads(store.path.read_text(encoding="utf-8"))
        config["configurations"][0]["goAttach"]["port"] = 2456
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
        assert app.query_one("#code-stop").disabled
        assert not app.query_one("#code-reconnect").display
        assert not session.closed
        await pilot.click("#area-containers")
        await pilot.click("#area-code")
        assert app.query_one("#code-stop").disabled
        assert not session.closed
        table.move_cursor(row=0)
        await pilot.pause()
        assert app.query_one("#code-stop").label == "Disconnect"
        assert session.profile.root == roots[0]
        assert session.profile.go_attach.port == 2345
        await pilot.click("#code-stop")
        assert session.closed
