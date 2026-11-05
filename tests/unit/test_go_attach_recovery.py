"""Explicit recovery from an unexpected Go attach transport loss."""

import asyncio
import json

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


async def test_unexpected_loss_offers_pinned_explicit_reconnect_with_pending_marks(
    attach_recovery_app,
):
    app, roots, _store = attach_recovery_app
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
        assert app.query_one("#code-stop").disabled

        # Selection changes cannot retarget the recovery action.
        app.query_one("#code-projects").move_cursor(row=1)
        await pilot.pause()
        await pilot.click("#code-reconnect")
        await until(pilot, lambda: len(FakeGoAttach.instances) == 2)
        await pilot.click("#code-reconnect")
        await pilot.pause()

        assert len(FakeGoAttach.instances) == 2
        second = FakeGoAttach.instances[1]
        assert second.profile.name == first.profile.name
        assert second.profile.root == roots[0]
        assert second.requested_breakpoints == {str(source.resolve()): (1,)}
        assert browser.breakpoints(roots[0], source) == (1,)


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


async def test_reconnect_rejects_pending_f5_and_stop_clears_recovery(attach_recovery_app):
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
        await pilot.click("#code-reconnect")
        await pilot.pause()

        assert len(FakeGoAttach.instances) == 1
        assert browser.breakpoints(roots[0], source) == marks == (1,)
        assert session.requested_breakpoints == {str(source.resolve()): (1,)}

        await pilot.click("#code-stop")
        await asyncio.wait_for(cancelled.wait(), 2)
        await until(pilot, lambda: "Stopped" in rendered(app, "#code-run-state"))
        assert not app.query_one("#code-reconnect").display
        assert browser.breakpoints(roots[0], source) == (1,)
        await pilot.click("#code-reconnect")
        await pilot.pause()
        await workspace.shutdown()
        assert len(FakeGoAttach.instances) == 1
        assert not app.query_one("#code-reconnect").display


async def test_reconnect_rejects_active_f5_and_stop_is_repeatable(attach_recovery_app):
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
        await pilot.click("#code-reconnect")
        await pilot.pause()

        assert len(FakeGoAttach.instances) == 1
        assert session.requested_breakpoints == {str(source.resolve()): (1,)}
        assert browser.breakpoints(roots[0], source) == marks == (1,)
        assert "Running: two" in rendered(app, "#code-run-state")

        await pilot.click("#code-stop")
        await until(pilot, lambda: rendered(app, "#code-run-state") == "Stopped")
        assert not app.query_one("#code-reconnect").display
        await pilot.click("#code-stop")
        await app.query_one("#code-workspace").shutdown()
        assert len(FakeGoAttach.instances) == 1
        assert not app.query_one("#code-reconnect").display


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
