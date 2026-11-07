"""Explicit recovery from an unexpected Go attach transport loss."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from test_code_debug_ui import debug_app, rendered, until
from test_go_attach_ui import FakeGoAttach

from debugpilot.tui import code_debug


@pytest.fixture
def attach_recovery_app(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    profile = config["configurations"][0]
    profile.pop("command", None)
    profile["goAttach"] = {
        "host": "127.0.0.1", "port": 2345, "remoteRoot": "/app"
    }
    store.path.write_text(json.dumps(config), encoding="utf-8")
    FakeGoAttach.instances = []
    monkeypatch.setattr(code_debug, "GoAttachSession", FakeGoAttach, raising=False)
    return app, roots, store


async def test_recovery_controls_follow_selected_profile_and_reconnect_pinned_config(
    attach_recovery_app,
):
    app, roots, store = attach_recovery_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        browser = app.query_one("#source-browser")
        source = roots[0] / "main.py"
        assert browser.open_source(roots[0], source, 1)
        await pilot.click("#source-breakpoint")
        marks = browser.breakpoints(roots[0], source)

        await pilot.press("shift+f5")
        await until(pilot, lambda: len(FakeGoAttach.instances) == 1)
        first = FakeGoAttach.instances[0]
        first.emit("transportClosed", message="peer disappeared")
        first.state = "closed"
        first.emit("state", state="closed")
        await pilot.pause()

        assert "Unexpected" in rendered(app, "#code-run-state")
        reconnect = app.query_one("#code-reconnect")
        assert reconnect.display
        assert browser.breakpoints(roots[0], source) == marks == (1,)
        pending = browser.query_one("Tree").root.children[0].children[0].label
        assert "Line 1 · pending" in str(pending)
        assert not app.query_one("#code-stop").disabled

        # Edited configuration cannot retarget the recovery context.
        config = json.loads(store.path.read_text(encoding="utf-8"))
        config["configurations"][0]["goAttach"]["port"] = 2456
        store.path.write_text(json.dumps(config), encoding="utf-8")
        workspace = app.query_one("#code-workspace")
        workspace.reload_profiles()
        table = app.query_one("#code-projects")
        table.move_cursor(row=1)
        await pilot.pause()
        assert not reconnect.display
        assert app.query_one("#code-stop").disabled
        # Hidden controls have no click target; the action must still not retarget.
        workspace.reconnect()
        await pilot.pause()
        assert len(FakeGoAttach.instances) == 1

        table.move_cursor(row=0)
        await pilot.pause()
        assert reconnect.display
        assert not app.query_one("#code-stop").disabled
        await pilot.click("#code-reconnect")
        await until(pilot, lambda: len(FakeGoAttach.instances) == 2)
        workspace.reconnect()
        await pilot.pause()

        assert len(FakeGoAttach.instances) == 2
        second = FakeGoAttach.instances[1]
        assert second.profile.name == first.profile.name
        assert second.profile.root == roots[0]
        assert second.profile.go_attach.port == 2345
        assert second.requested_breakpoints == {str(source.resolve()): (1,)}
        assert browser.breakpoints(roots[0], source) == (1,)
        await pilot.click("#code-stop")
        assert second.closed and not app.query_one("#code-reconnect").display


async def _disconnect_unexpectedly(pilot, app, roots):
    browser = app.query_one("#source-browser")
    source = roots[0] / "main.py"
    assert browser.open_source(roots[0], source, 1)
    await pilot.click("#source-breakpoint")
    marks = browser.breakpoints(roots[0], source)
    await pilot.press("shift+f5")
    await until(pilot, lambda: len(FakeGoAttach.instances) == 1)
    session = FakeGoAttach.instances[0]
    session.emit("transportClosed", message="peer disappeared")
    session.state = "closed"
    session.emit("state", state="closed")
    await until(pilot, lambda: app.query_one("#code-reconnect").display)
    return browser, source, marks, session


async def test_reconnect_coexists_with_other_pending_run_and_stop_is_profile_local(
    attach_recovery_app,
):
    app, roots, _store = attach_recovery_app
    started = asyncio.Event()
    cancelled = asyncio.Event()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        browser, source, marks, session = await _disconnect_unexpectedly(pilot, app, roots)
        workspace = app.query_one("#code-workspace")
        app.query_one("#code-projects").move_cursor(row=1)
        await pilot.pause()

        async def pending_run(profile):
            assert profile.command
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        workspace._start = pending_run
        await pilot.press("f5")
        await asyncio.wait_for(started.wait(), 2)
        app.query_one("#code-projects").move_cursor(row=0)
        await pilot.pause()
        await pilot.click("#code-reconnect")
        await until(pilot, lambda: len(FakeGoAttach.instances) == 2)
        assert started.is_set() and not cancelled.is_set()
        assert browser.breakpoints(roots[0], source) == marks == (1,)
        assert session.requested_breakpoints == {str(source.resolve()): (1,)}
        assert FakeGoAttach.instances[1].requested_breakpoints == {
            str(source.resolve()): (1,)
        }

        await pilot.click("#code-stop")
        assert FakeGoAttach.instances[1].closed
        assert not cancelled.is_set(), "stopping attach cancelled the other profile startup"
        app.query_one("#code-projects").move_cursor(row=1)
        await pilot.pause()
        await pilot.click("#code-stop")
        await asyncio.wait_for(cancelled.wait(), 2)
        await until(pilot, lambda: "Stopped" in rendered(app, "#code-run-state"))
        assert not app.query_one("#code-reconnect").display
        assert browser.breakpoints(roots[0], source) == (1,)
        await workspace.shutdown()
        assert len(FakeGoAttach.instances) == 2
        assert FakeGoAttach.instances[0].closed


async def test_reconnect_coexists_with_other_active_run_and_stop_is_repeatable(attach_recovery_app):
    app, roots, _store = attach_recovery_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        browser, source, marks, session = await _disconnect_unexpectedly(pilot, app, roots)
        second_source = roots[1] / "main.py"
        second_source.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        app.query_one("#code-projects").move_cursor(row=1)
        await pilot.pause()
        await pilot.press("f5")
        await until(pilot, lambda: app.query_one("#code-terminal").active)
        run_context = app.query_one("#code-terminal").selected_context
        run_session = run_context.session
        app.query_one("#code-projects").move_cursor(row=0)
        await pilot.pause()
        await pilot.click("#code-reconnect")
        await until(pilot, lambda: len(FakeGoAttach.instances) == 2)

        assert run_context.active and run_session is not None
        assert session.requested_breakpoints == {str(source.resolve()): (1,)}
        assert browser.breakpoints(roots[0], source) == marks == (1,)
        assert FakeGoAttach.instances[1].requested_breakpoints == {
            str(source.resolve()): (1,)
        }

        await pilot.click("#code-stop")
        assert FakeGoAttach.instances[1].closed
        assert run_context.active, "stopping attach stopped the other profile's process"
        await pilot.click("#code-stop")
        app.query_one("#code-projects").move_cursor(row=1)
        await pilot.pause()
        await pilot.click("#code-stop")
        await until(pilot, lambda: not run_context.active)
        await app.query_one("#code-workspace").shutdown()
        assert len(FakeGoAttach.instances) == 2
        assert all(item.closed for item in FakeGoAttach.instances)


async def test_stop_on_inactive_unexpected_attach_retires_only_selected_recovery(
    attach_recovery_app,
):
    app, roots, _store = attach_recovery_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        browser, source, marks, first = await _disconnect_unexpectedly(pilot, app, roots)
        assert app.query_one("#code-stop").disabled is False
        await pilot.click("#code-stop")
        assert not app.query_one("#code-reconnect").display
        assert rendered(app, "#code-run-state") == (
            "Disconnected; target remains managed by Containers"
        )
        assert browser.breakpoints(roots[0], source) == marks == (1,)
        assert first.closed


async def test_deliberate_disconnect_does_not_offer_recovery(attach_recovery_app):
    app, _roots, _store = attach_recovery_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("shift+f5")
        await until(pilot, lambda: len(FakeGoAttach.instances) == 1)
        await pilot.click("#code-stop")
        assert not app.query_one("#code-reconnect").display
        assert "Disconnected" in rendered(app, "#code-run-state")
        assert len(FakeGoAttach.instances) == 1


async def test_local_debug_does_not_offer_attach_recovery(monkeypatch, tmp_path):
    from test_code_debug_ui import FakeDebug

    monkeypatch.setattr(FakeDebug, "instances", [])
    monkeypatch.setattr(code_debug, "PythonDebugSession", FakeDebug)
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("shift+f5")
        await until(pilot, lambda: bool(FakeDebug.instances))
        session = FakeDebug.instances[-1]
        session.emit("transportClosed", message="local debugger ended")
        session.state = "closed"
        session.emit("state", state="closed")
        await pilot.pause()
        assert not app.query_one("#code-reconnect").display
        assert len(FakeDebug.instances) == 1


async def test_lost_attach_with_command_stays_one_session_per_profile(monkeypatch, tmp_path):
    app, _roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    config["configurations"][0]["goAttach"] = {
        "host": "127.0.0.1", "port": 2345, "remoteRoot": "/app"
    }
    store.path.write_text(json.dumps(config), encoding="utf-8")
    FakeGoAttach.instances = []
    monkeypatch.setattr(code_debug, "GoAttachSession", FakeGoAttach, raising=False)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("shift+f5")
        await until(pilot, lambda: len(FakeGoAttach.instances) == 1)
        lost = FakeGoAttach.instances[0]
        lost.emit("transportClosed", message="peer disappeared")
        lost.state = "closed"
        lost.emit("state", state="closed")
        await pilot.pause()
        workspace = app.query_one("#code-workspace")
        pane = app.query_one("#code-terminal")

        app.action_run_code()
        await pilot.pause()
        assert "one" not in pane.contexts, "F5 started a run beside a recovering attach"
        assert "Unexpected" in rendered(app, "#code-run-state")
        assert app.query_one("#code-reconnect").display

        # Reconnect must refuse a live run on this profile, however it got there.
        pane.contexts["one"] = SimpleNamespace(pending=False, active=True, stopping=False)
        workspace.reconnect()
        await pilot.pause()
        assert len(FakeGoAttach.instances) == 1, "Reconnect attached beside a live run"
        del pane.contexts["one"]

        workspace.reconnect()
        await until(pilot, lambda: len(FakeGoAttach.instances) == 2)
        await workspace.shutdown()
