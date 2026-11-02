"""Regressions for terminal state colliding with Textual's message lifecycle."""

import pytest
from textual.app import App, ComposeResult
from textual.events import Key
from textual.message import Message
from textual.widgets import Static

from debugpilot.tui.terminal_view import TerminalPane


def test_terminal_constructor_accepts_messages_before_mount():
    pane = TerminalPane()
    assert not pane.active
    assert pane.post_message(Key("x", "x"))


def test_terminal_blank_frame_uses_supported_pyte_attributes():
    frame = TerminalPane().render()
    assert [len(row) for row in frame.plain.splitlines()] == [80] * 24


class LifecycleProbe(Message):
    """Check message delivery without queuing a keystroke into the next session."""


class FakeSession:
    def __init__(self, *, on_output, on_exit):
        self.on_output = on_output
        self.on_exit = on_exit
        self.close_count = 0
        self.writes = []

    async def open_host(self, cwd, rows, columns):
        self.cwd = cwd

    async def close_session(self):
        self.close_count += 1
        self.on_exit()

    def write(self, text):
        self.writes.append(text)

    def resize(self, rows, columns):
        pass


class LifecycleApp(App):
    def __init__(self, pane):
        super().__init__()
        self.pane = pane

    def compose(self) -> ComposeResult:
        yield self.pane
        yield Static("ready", id="lifecycle-marker")


@pytest.mark.asyncio
async def test_fake_session_close_and_exit_leave_mounted_widget_reusable(monkeypatch, tmp_path):
    made = []

    def factory(**callbacks):
        session = FakeSession(**callbacks)
        made.append(session)
        return session

    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", factory)
    pane = TerminalPane()
    app = LifecycleApp(pane)
    async with app.run_test(size=(30, 8)) as pilot:
        assert pane.is_mounted
        assert made == []
        await pane.open_host(tmp_path)
        assert pane.active_kind == "host"
        await pane.close_session()
        await pilot.pause()
        assert not pane.active
        assert pane.post_message(LifecycleProbe())
        marker = app.query_one("#lifecycle-marker", Static)
        marker.update("session closed; widget alive")
        await pane.open_host(tmp_path)
        await pilot.press("x")
        assert made[1].writes == ["x"]
        made[1].on_exit()
        await pilot.pause()
        assert not pane.active
        assert pane.post_message(LifecycleProbe())
        await pane.open_host(tmp_path)
        await pilot.pause()
        assert pane.active
        assert "widget alive" in str(marker.render())
    assert not pane.active
    assert [session.close_count for session in made] == [1, 1, 1]
