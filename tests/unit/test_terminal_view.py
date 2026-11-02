from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rich.color import ColorType
from textual.app import App, ComposeResult
from textual.events import Paste

from debugpilot.core.models import ContainerInfo
from debugpilot.tui.terminal_view import TerminalPane


class FakeSession:
    def __init__(self, *, on_output, on_exit=None):
        self.on_output = on_output
        self.on_exit = on_exit
        self.writes: list[str] = []
        self.sizes: list[tuple[int, int]] = []
        self.closed = False

    async def open_host(self, cwd, rows, columns):
        self.host_open = (cwd, rows, columns)

    async def open_container(self, container, endpoint, cwd, rows, columns):
        self.container_open = (container, endpoint, cwd, rows, columns)

    def write(self, text):
        self.writes.append(text)

    def resize(self, rows, columns):
        self.sizes.append((rows, columns))

    async def close_session(self):
        self.closed = True

    def emit(self, text):
        self.on_output(text)

    def exit(self):
        if self.on_exit:
            self.on_exit()


class TerminalApp(App):
    CSS = "TerminalPane { width: 12; height: 4; }"
    BINDINGS = [("c", "parent_shortcut", "Parent shortcut")]

    def __init__(self, pane: TerminalPane):
        super().__init__()
        self.pane = pane
        self.shortcut_count = 0

    def compose(self) -> ComposeResult:
        yield self.pane

    def action_parent_shortcut(self):
        self.shortcut_count += 1


@pytest.mark.asyncio
async def test_construct_mount_and_open_use_public_context_api(monkeypatch, tmp_path):
    made: list[FakeSession] = []

    def factory(*, on_output, on_exit=None):
        session = FakeSession(on_output=on_output, on_exit=on_exit)
        made.append(session)
        return session

    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", factory)
    pane = TerminalPane()
    assert pane.active is False
    async with TerminalApp(pane).run_test() as _pilot:
        assert made == []
        await pane.open_host(tmp_path)
        assert len(made) == 1
        assert pane.active is True
        assert pane.active_kind == "host"
        assert pane.context.cwd == tmp_path
        await pane.close_session()
        await pane.close_session()
        assert pane.active is False
        assert made[0].closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["host", "container"])
async def test_screen_geometry_resize_vt_style_and_cursor_are_rendered(monkeypatch, tmp_path, kind):
    made: list[FakeSession] = []

    def factory(*, on_output, on_exit=None):
        session = FakeSession(on_output=on_output, on_exit=on_exit)
        made.append(session)
        return session

    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", factory)
    pane = TerminalPane()
    async with TerminalApp(pane).run_test() as _pilot:
        if kind == "host":
            await pane.open_host(tmp_path)
            assert made[0].host_open == (tmp_path, 4, 12)
        else:
            container = ContainerInfo(
                id="a" * 64, name="sample", image="example", state="running",
                created_at=datetime.now(UTC),
            )
            await pane.open_container(container, "local", tmp_path)
            assert made[0].container_open == (container, "local", tmp_path, 4, 12)
        assert [len(row) for row in pane.render().plain.splitlines()] == [12] * 4
        made[0].emit("abcdefghijklM")
        await asyncio.sleep(0)
        assert pane.render().plain.splitlines() == [
            "abcdefghijkl", "M           ", "            ", "            ",
        ]
        made[0].emit("\x1b[2J\x1b[H")
        await _pilot.pause()
        pane.styles.width = 14
        await _pilot.pause()
        assert made[0].sizes[-1] == (4, 14)
        assert [len(row) for row in pane.render().plain.splitlines()] == [14] * 4
        made[0].emit("\x1b[31mred\x1b[0m\x1b[2;3H")
        await asyncio.sleep(0)
        rendered = pane.render()
        assert "red" in rendered.plain
        red_offset = rendered.plain.index("red")
        red_style = rendered.get_style_at_offset(pane.app.console, red_offset)
        assert red_style.color.type == ColorType.STANDARD
        assert red_style.color.number == 1
        cursor_offset = 14 + 1 + 2
        assert rendered.get_style_at_offset(pane.app.console, cursor_offset).reverse is True
        made[0].emit("\x1b]52;c;clipboard\x07\x1b]0;private-title\x07\x1b]8;;https://example.invalid\x07link\x1b]8;;\x07")
        await asyncio.sleep(0)
        assert "clipboard" not in pane.render().plain
        assert "private-title" not in pane.render().plain
        assert "https://example.invalid" not in pane.render().plain
        await pane.close_session()


@pytest.mark.asyncio
async def test_text_keys_paste_and_escape_do_not_trigger_parent_shortcuts(monkeypatch, tmp_path):
    made: list[FakeSession] = []

    def factory(*, on_output, on_exit=None):
        session = FakeSession(on_output=on_output, on_exit=on_exit)
        made.append(session)
        return session

    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", factory)
    escaped: list[bool] = []
    pane = TerminalPane(escape_hook=lambda: escaped.append(True))
    app = TerminalApp(pane)
    async with app.run_test() as pilot:
        await pane.open_host(tmp_path)
        await pilot.press("space", "c", "up", "enter", "ctrl+c", "escape")
        app.post_message(Paste("pasted ñ"))
        await pilot.pause()
        assert made[0].writes == [" ", "c", "\x1b[A", "\r", "\x03", "pasted ñ"]
        assert escaped == [True]
        assert app.shortcut_count == 0
        await pane.close_session()


@pytest.mark.asyncio
async def test_output_queued_by_replaced_context_is_ignored(monkeypatch, tmp_path):
    made: list[FakeSession] = []

    def factory(*, on_output, on_exit=None):
        session = FakeSession(on_output=on_output, on_exit=on_exit)
        made.append(session)
        return session

    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", factory)
    pane = TerminalPane()
    async with TerminalApp(pane).run_test() as _pilot:
        await pane.open_host(tmp_path)
        made[0].emit("stale-context")
        await pane.open_host(tmp_path)
        await asyncio.sleep(0)
        assert pane.render().plain.splitlines() == [" " * 12] * 4
        made[1].emit("current-context")
        await asyncio.sleep(0)
        assert pane.render().plain.splitlines() == [
            "current-cont", "ext         ", "            ", "            ",
        ]
        made[1].exit()
        await asyncio.sleep(0)
        assert pane.active is False
        await pane.close_session()


def test_container_context_is_exposed_without_shell_start(monkeypatch, tmp_path):
    container = ContainerInfo(
        id="a" * 64, name="sample", image="example", state="running",
        created_at=datetime.now(UTC),
    )
    pane = TerminalPane()
    assert pane.active is False
    assert pane.context is None
    assert container.id == "a" * 64
    assert Path(tmp_path).is_absolute()
