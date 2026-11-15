"""Paused-session controls and view state survive inspection and frame changes."""

import asyncio

import pytest
from test_code_debug_ui import FakeDebug, debug_app, until
from textual.widgets import DataTable, RichLog

from debugpilot.debugger import DebugError
from debugpilot.tui import code_debug


class TwoFrameDebug(FakeDebug):
    resumed = False

    async def stack(self):
        path = str(self.profile.root / "main.py")
        return [
            {"id": 1, "name": "inner", "line": 4, "source": {"path": path}},
            {"id": 2, "name": "outer", "line": 2, "source": {"path": path}},
        ]

    async def scopes(self, frame):
        return [{"name": "Locals", "variablesReference": frame}]

    async def variables(self, reference):
        return [{"name": "seen", "value": f"frame-{reference}", "variablesReference": 0}]

    async def continue_execution(self):
        self.resumed = True
        self.state = "running"
        self.emit("state", state="running")

    def pause_again(self):
        self.state = "running"
        self.emit("state", state="running")
        self.state = "stopped"
        self.emit("state", state="stopped")
        self.emit("stopped", threadId=1)


def variables_text(app):
    return app.query_one("#code-variables").text


async def start_debug(pilot, app, monkeypatch, session_class):
    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "PythonDebugSession", session_class)
    await pilot.click("#area-code")
    await pilot.click("#code-debug-start")
    await until(pilot, lambda: len(FakeDebug.instances) == 1)
    return FakeDebug.instances[0]


async def fill_output_and_scroll_home(pilot, app, session):
    for index in range(200):
        session.on_output("stdout", f"line {index}")
    await pilot.pause()
    log = app.query_one("#code-debug-output", RichLog)
    log.scroll_home(animate=False)
    await pilot.pause()
    assert log.max_scroll_y > 0 and log.scroll_y == 0
    return log, len(log.lines)


@pytest.mark.parametrize(
    ("failing", "rows"), [("stack", 0), ("scopes", 2), ("variables", 2)]
)
async def test_failed_pause_inspection_can_still_continue(
    monkeypatch, tmp_path, failing, rows
):
    class FailingDebug(TwoFrameDebug):
        pass

    async def fail(_self, *_args):
        raise DebugError("inspection failed")

    setattr(FailingDebug, failing, fail)
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        session = await start_debug(pilot, app, monkeypatch, FailingDebug)
        button = app.query_one("#code-continue")
        await until(pilot, lambda: not button.disabled)
        await until(pilot, lambda: app.query_one("#code-stack", DataTable).row_count == rows)
        await pilot.click("#code-continue")
        await until(pilot, lambda: session.resumed)
        await app.query_one("#code-workspace").shutdown()


async def test_controls_and_stack_do_not_wait_for_slow_variables(monkeypatch, tmp_path):
    release = asyncio.Event()

    class SlowDebug(TwoFrameDebug):
        async def variables(self, reference):
            await release.wait()
            return await super().variables(reference)

    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        await start_debug(pilot, app, monkeypatch, SlowDebug)
        stack = app.query_one("#code-stack", DataTable)
        await until(pilot, lambda: stack.row_count == 2)
        assert not app.query_one("#code-continue").disabled
        assert "frame-" not in variables_text(app)
        release.set()
        await until(pilot, lambda: "frame-1" in variables_text(app))
        await app.query_one("#code-workspace").shutdown()


async def test_selected_frame_keeps_cursor_and_output_scroll(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        session = await start_debug(pilot, app, monkeypatch, TwoFrameDebug)
        await until(pilot, lambda: "frame-1" in variables_text(app))
        log, line_count = await fill_output_and_scroll_home(pilot, app, session)
        stack = app.query_one("#code-stack", DataTable)
        stack.focus()
        stack.move_cursor(row=1)
        await pilot.pause()
        await pilot.press("enter")
        await until(pilot, lambda: "frame-2" in variables_text(app))
        await pilot.pause()

        assert stack.cursor_row == 1, "selecting a frame moved the stack cursor"
        assert log.scroll_y == 0, "selecting a frame lost the output scroll position"
        assert len(log.lines) == line_count
        assert not app.query_one("#code-continue").disabled

        profiles = app.query_one("#code-projects", DataTable)
        profiles.move_cursor(row=1)
        await pilot.pause()
        profiles.move_cursor(row=0)
        await pilot.pause()
        assert app.query_one("#code-stack", DataTable).cursor_row == 1
        assert "frame-2" in variables_text(app)
        await app.query_one("#code-workspace").shutdown()


async def test_next_pause_keeps_output_scroll_and_restarts_at_top_frame(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        session = await start_debug(pilot, app, monkeypatch, TwoFrameDebug)
        await until(pilot, lambda: "frame-1" in variables_text(app))
        log, line_count = await fill_output_and_scroll_home(pilot, app, session)
        stack = app.query_one("#code-stack", DataTable)
        stack.focus()
        stack.move_cursor(row=1)
        await pilot.pause()
        await pilot.press("enter")
        await until(pilot, lambda: "frame-2" in variables_text(app))

        session.pause_again()
        await until(pilot, lambda: "frame-1" in variables_text(app))
        await pilot.pause()

        assert log.scroll_y == 0, "a new pause lost the output scroll position"
        assert len(log.lines) == line_count
        assert stack.row_count == 2 and stack.cursor_row == 0
        await app.query_one("#code-workspace").shutdown()
