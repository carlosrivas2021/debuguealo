"""Public Code UI behavior for Go debugging and optional exit status."""

import asyncio
import json

import pytest
from test_code_debug_ui import debug_app, rendered, until
from textual.widgets import DataTable, Tree

from debugpilot.tui import code_debug
from debugpilot.tui.source_browser import SourceBrowser


class FakeGoDebug:
    instances = []
    failure = None
    reported_exit_code = None

    def __init__(self, on_event, on_output):
        self.on_event = on_event
        self.on_output = on_output
        self.events = asyncio.Queue()
        self.state = "idle"
        self.exit_code = type(self).reported_exit_code
        self.verified_breakpoints = {}
        self.requested_breakpoints = {}
        self.instances.append(self)

    def emit(self, event, **body):
        message = {"event": event, "body": body}
        self.events.put_nowait(message)
        self.on_event(message)

    async def start(self, profile, breakpoints):
        self.profile = profile
        self.requested_breakpoints = dict(breakpoints)
        self.state = "starting"
        self.emit("state", state="starting")
        if self.failure:
            from debugpilot.debugger import DebugError

            raise DebugError(self.failure)
        self.state = "closed"
        self.emit("state", state="closed")

    async def close(self):
        self.state = "closed"


@pytest.fixture
async def go_app(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    source = roots[0] / "main.go"
    source.write_text(
        'package main\n\nimport "fmt"\n\nfunc main() {\n'
        '\tanswer := 41\n\tanswer++\n\tfmt.Printf("RESULT:%d\\n", answer)\n}\n',
        encoding="utf-8",
    )
    config = json.loads(store.path.read_text(encoding="utf-8"))
    config["configurations"][0]["command"] = ["go", "run", "main.go"]
    store.path.write_text(json.dumps(config), encoding="utf-8")
    return app, roots, store


async def test_go_shift_f5_dispatch_and_unknown_exit_are_explicit(
    monkeypatch, go_app
):
    app, roots, store = go_app
    FakeGoDebug.instances = []
    monkeypatch.setattr(code_debug, "GoDebugSession", FakeGoDebug)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("shift+f5")
        await until(pilot, lambda: bool(FakeGoDebug.instances))
        assert FakeGoDebug.instances[0].profile.command == ("go", "run", "main.go")
        await until(
            pilot,
            lambda: "finalizado; código de salida no disponible"
            in rendered(app, "#code-run-state"),
        )
        state = rendered(app, "#code-run-state")
        assert "Exited: None" not in state
        assert not app.query_one("#code-run").disabled
        assert app.query_one("#code-stack", DataTable).row_count == 0


async def test_go_missing_delv_is_actionable_without_run_fallback(monkeypatch, go_app):
    app, roots, store = go_app
    original = store.path.read_bytes()
    FakeGoDebug.instances = []
    FakeGoDebug.failure = "Delve (dlv) is required. No run-mode fallback."
    monkeypatch.setattr(code_debug, "GoDebugSession", FakeGoDebug)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("shift+f5")
        await until(pilot, lambda: "Unable to debug one" in rendered(app, "#code-run-state"))
        assert "Delve (dlv) is required" in rendered(app, "#code-run-state")
        assert not app.query_one("#code-terminal").active
        assert store.path.read_bytes() == original
        assert not app.query_one("#code-run").disabled
    FakeGoDebug.failure = None


async def test_go_reported_exit_code_remains_accurate(monkeypatch, go_app):
    app, roots, store = go_app
    FakeGoDebug.instances = []
    FakeGoDebug.failure = None
    FakeGoDebug.reported_exit_code = 23
    monkeypatch.setattr(code_debug, "GoDebugSession", FakeGoDebug)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("shift+f5")
        await until(pilot, lambda: "Exited: 23" in rendered(app, "#code-run-state"))
        assert "finalizado; código de salida no disponible" not in rendered(
            app, "#code-run-state"
        )
    FakeGoDebug.reported_exit_code = None


async def test_go_f5_keeps_original_argv_without_debug_dispatch(monkeypatch, go_app):
    app, roots, store = go_app
    FakeGoDebug.instances = []
    started = []

    async def run(profile):
        started.append(profile.command)

    async with app.run_test(size=(120, 45)) as pilot:
        workspace = app.query_one("#code-workspace")
        monkeypatch.setattr(workspace, "_start", run)
        monkeypatch.setattr(code_debug, "GoDebugSession", FakeGoDebug)
        await pilot.click("#area-code")
        await pilot.press("f5")
        await until(pilot, lambda: bool(started))
        assert started == [("go", "run", "main.go")]
        assert FakeGoDebug.instances == []


async def test_go_real_breakpoint_variables_continue_output_and_unknown_status(go_app):
    app, roots, _ = go_app
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click("#area-code")
        browser = app.query_one(SourceBrowser)
        tree = browser.query_one(Tree)
        tree.select_node(next(node for node in tree.root.children if str(node.label) == "main.go"))
        await pilot.pause()
        browser.query_one("#source-text").move_cursor((6, 0))
        await pilot.click("#source-breakpoint")
        await pilot.press("shift+f5")
        async with asyncio.timeout(20):
            while "answer = 41" not in rendered(app, "#code-variables"):
                assert "Unable to debug" not in rendered(app, "#code-run-state")
                await pilot.pause(0.02)
        assert "41" in rendered(app, "#code-variables")
        assert app.query_one("#code-stack", DataTable).row_count >= 1
        await pilot.click("#code-continue")
        async with asyncio.timeout(20):
            while "finalizado; código de salida no disponible" not in rendered(
                app, "#code-run-state"
            ) and "Exited:" not in rendered(app, "#code-run-state"):
                await pilot.pause(0.02)
        output = "\n".join(line.text for line in app.query_one("#code-debug-output").lines)
        assert "RESULT:42" in output
        state = rendered(app, "#code-run-state")
        assert "finalizado; código de salida no disponible" in state or "Exited: 0" in state
        assert "Exited: None" not in state
        assert browser.breakpoints(roots[0], roots[0] / "main.go") == (7,)
