"""Selecting text re-renders the terminal on every mouse move, so a render must stay cheap."""

import threading
import time

import pyte
from rich.console import Console
from rich.style import Style

from debugpilot.tui import clipboard
from debugpilot.tui.terminal_view import TerminalPane


class SizedPane(TerminalPane):
    def __init__(self, rows, columns):
        super().__init__()
        self._size = (rows, columns)
        self._screen = pyte.Screen(columns, rows)
        self._stream = pyte.Stream(self._screen)

    def _screen_size(self):
        return self._size


def per_cell_reference(pane):
    """The previous rendering: one styled character at a time."""
    rows, columns = pane._screen_size()
    screen, cursor = pane._screen, pane._screen.cursor
    styles = []
    for y in range(rows):
        for x in range(columns):
            cell = screen.buffer[y][x]
            styles.append((cell.data, Style(
                color=pane._terminal_color(cell.fg), bgcolor=pane._terminal_color(cell.bg),
                bold=cell.bold, italic=cell.italics, underline=cell.underscore,
                strike=cell.strikethrough,
                reverse=cell.reverse or (not cursor.hidden and cursor.x == x and cursor.y == y),
            )))
    return styles


def rendered_cells(pane):
    text = pane.render()
    console = Console()
    cells = []
    for offset, character in enumerate(text.plain):
        if character != "\n":
            cells.append((character, text.get_style_at_offset(console, offset)))
    return cells


def test_render_matches_the_per_cell_styles_exactly():
    pane = SizedPane(4, 20)
    pane._stream.feed("plain \x1b[31mred\x1b[1m bold\x1b[0m"
                      "\r\n\x1b[7mrev\x1b[0m \x1b[42;3mgreen it\x1b[0m"
                      "\r\n\x1b[4munder\x1b[9mstrike\x1b[0m\x1b[3;4H")
    assert rendered_cells(pane) == per_cell_reference(pane)

    pane._stream.feed("\x1b[?25l")  # a hidden cursor is not drawn
    assert rendered_cells(pane) == per_cell_reference(pane)


def test_plain_output_is_one_span_per_row_not_one_per_character():
    pane = SizedPane(24, 80)
    pane._stream.feed("\x1b[?25l" + "".join(f"line {i}\r\n" for i in range(23)))

    assert len(pane.render().spans) <= 24


def test_native_copy_does_not_block_the_caller(monkeypatch):
    """pbcopy and friends run off the UI thread; a slow one must not freeze the app."""
    from debugpilot.tui.app import DebugPilotApp

    release, copied = threading.Event(), []

    def slow_copy(text):
        release.wait(5)
        copied.append(text)
        return True

    monkeypatch.setattr(clipboard, "copy_native", slow_copy)
    monkeypatch.setattr("textual.app.App.copy_to_clipboard", lambda self, text: None)
    start = time.perf_counter()
    DebugPilotApp.copy_to_clipboard(object.__new__(DebugPilotApp), "selected text")
    assert time.perf_counter() - start < 0.5
    assert copied == []

    release.set()
    deadline = time.monotonic() + 5
    while not copied and time.monotonic() < deadline:
        time.sleep(0.01)
    assert copied == ["selected text"]
