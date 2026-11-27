from __future__ import annotations

import asyncio
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import pyte
from pyte.screens import Margins
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.events import Key, MouseScrollDown, MouseScrollUp, Paste
from textual.widget import Widget

from debugpilot.core.models import ContainerInfo
from debugpilot.terminal import TerminalSession

SCREEN_ROWS = 200
SCREEN_COLUMNS = 500
MAX_FEED_CHARS = 64 * 1024
# Distinct cell styles kept between renders; a screen rarely uses more than a few dozen.
MAX_CACHED_STYLES = 1024
# Lines kept above the screen for scrolling back, like a terminal's scrollback.
SCROLLBACK_LINES = 2000
# Lines one turn of the mouse wheel moves.
SCROLL_STEP = 3
SCROLLED_STYLE = Style(reverse=True)


class ScrollbackScreen(pyte.Screen):
    """A pyte screen that keeps the lines scrolled off its top.

    pyte.HistoryScreen jumps back to the bottom on every new output, which makes reading
    back impossible while a program keeps printing; this only records the lines.
    """

    def __init__(self, columns: int, lines: int) -> None:
        super().__init__(columns, lines)
        self.scrollback: deque = deque(maxlen=SCROLLBACK_LINES)
        # Lines ever kept, so a view scrolled back can stay on the same text.
        self.kept = 0

    def keep(self, line) -> None:
        self.scrollback.append(line)
        self.kept += 1

    def index(self) -> None:
        top, bottom = self.margins or Margins(0, self.lines - 1)
        # Only a whole-screen scroll is history; a scrolling region inside a full-screen
        # program (a status bar, an editor) is not.
        if self.cursor.y == bottom and top == 0:
            self.keep(self.buffer[top])
        super().index()


def resize_screen(screen: pyte.Screen, lines: int, columns: int) -> None:
    """Resize like pyte, but keep output when the screen shrinks.

    pyte clips a shrinking screen at the top, which erases output a process printed
    before the widget got its real size. Drop from the top only the rows needed to keep
    the cursor on screen and cut the rest below it.
    """
    if lines >= screen.lines:
        screen.resize(lines=lines, columns=columns)
        return
    screen.resize(lines=screen.lines, columns=columns)
    drop = max(0, screen.cursor.y + 1 - lines)
    if isinstance(screen, ScrollbackScreen):
        for y in range(drop):
            screen.keep(screen.buffer[y])
    kept = {y - drop: row for y, row in screen.buffer.items() if drop <= y < drop + lines}
    screen.buffer.clear()
    screen.buffer.update(kept)
    screen.cursor.y -= drop
    screen.lines = lines
    screen.set_margins()
    screen.dirty.update(range(lines))


REPORT_START = "\x1b]7;"
# file://host/path, ended by BEL or ST (ESC \\).
FOLDER_REPORT = re.compile(r"\x1b\]7;([^\x07\x1b]*)(?:\x07|\x1b\\)")
MAX_REPORT = 4096


def _report_folder(value: str) -> Path | None:
    if not value.startswith("file://"):
        return None
    slash = value.find("/", len("file://"))
    return Path(value[slash:]) if slash != -1 else None


@dataclass(frozen=True)
class TerminalContext:
    kind: str
    cwd: Path
    container: ContainerInfo | None = None
    endpoint: str | None = None


class TerminalPane(Widget):
    """Native PTY display/input widget. Construction and mount never start a shell."""

    can_focus = True
    # A live shell disables the app shortcuts so their keys reach the process;
    # advertising Esc keeps the footer from going blank with no way back.
    BINDINGS = [Binding("escape", "release_focus", "Back to list")]

    def __init__(self, *, escape_hook=None, exit_hook=None, cwd_hook=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._escape_hook = escape_hook
        # Called when the shell ends on its own (`exit`), never on an explicit close.
        self._exit_hook = exit_hook
        # Called with the shell's folder each time it reports a new one (OSC 7).
        self._cwd_hook = cwd_hook
        self.cwd: Path | None = None
        self._report_pending = ""
        self._session: TerminalSession | None = None
        self._terminal_context: TerminalContext | None = None
        self._screen = ScrollbackScreen(80, 24)
        # Lines scrolled back from the bottom; 0 follows the output.
        self._scroll = 0
        self._stream = pyte.Stream(self._screen)
        # Textual owns MessagePump._closed; session state must not stop its event loop.
        self._session_closed = True
        self._generation = 0
        self._styles: dict[tuple, Style] = {}

    @property
    def active(self) -> bool:
        return self._session is not None and not self._session_closed

    @property
    def context(self) -> TerminalContext | None:
        return self._terminal_context

    @property
    def active_kind(self) -> str | None:
        return self._terminal_context.kind if self.active and self._terminal_context else None

    async def open_host(self, cwd: Path) -> None:
        await self._open(TerminalContext("host", Path(cwd)))

    async def open_container(self, container: ContainerInfo, endpoint: str, cwd: Path) -> None:
        await self._open(TerminalContext("container", Path(cwd), container, endpoint))

    async def _open(self, context: TerminalContext) -> None:
        await self.close_session()
        self._terminal_context = context
        self._session_closed = False
        self.cwd, self._report_pending = None, ""
        rows, columns = self._screen_size()
        self._screen = ScrollbackScreen(columns=columns, lines=rows)
        self._scroll = 0
        self._stream = pyte.Stream(self._screen)
        loop = asyncio.get_running_loop()
        generation = self._generation
        self._session = self._make_session(
            on_output=lambda text: loop.call_soon_threadsafe(self._accept_output, generation, text),
            on_exit=lambda: loop.call_soon_threadsafe(self._accept_exit, generation),
        )
        try:
            await self._start_session(context)
        except BaseException:
            await self.close_session()
            raise
        self.focus()

    def _make_session(self, **callbacks):
        return TerminalSession(**callbacks)

    async def _start_session(self, context: TerminalContext) -> None:
        if context.kind == "host":
            await self._session.open_host(context.cwd, *self._screen_size())
        else:
            await self._session.open_container(
                context.container, context.endpoint, context.cwd, *self._screen_size()
            )

    async def on_unmount(self) -> None:
        await self.close_session()

    async def close_session(self) -> None:
        session, self._session = self._session, None
        self._session_closed = True
        self._generation += 1
        if session is not None:
            await session.close_session()

    def _screen_size(self) -> tuple[int, int]:
        return min(SCREEN_ROWS, max(2, self.size.height or 24)), min(
            SCREEN_COLUMNS, max(2, self.size.width or 80)
        )

    def _take_folder_reports(self, text: str) -> str:
        """Remove OSC 7 folder reports from the output and remember the last folder."""
        text = self._report_pending + text
        self._report_pending = ""
        for match in FOLDER_REPORT.finditer(text):
            folder = _report_folder(match.group(1))
            if folder is not None and folder != self.cwd:
                self.cwd = folder
                if self._cwd_hook is not None:
                    self._cwd_hook(folder)
        text = FOLDER_REPORT.sub("", text)
        # A report split between two reads waits for its end; so does its first bytes.
        start = text.rfind(REPORT_START)
        if start == -1:
            start = next((len(text) - size for size in range(len(REPORT_START) - 1, 0, -1)
                          if text.endswith(REPORT_START[:size])), -1)
        if start != -1 and len(text) - start <= MAX_REPORT:
            text, self._report_pending = text[:start], text[start:]
        return text

    def _accept_output(self, generation: int, text: str) -> None:
        if self._session_closed or generation != self._generation:
            return
        text = self._take_folder_reports(text)
        kept = getattr(self._screen, "kept", 0)
        self._stream.feed(text[:MAX_FEED_CHARS])
        if self._scroll:
            # Reading back: stay on the same text while new lines arrive below.
            self._scroll = min(self._scroll + getattr(self._screen, "kept", 0) - kept,
                               self._scrollback_size())
        self.refresh()

    def _accept_exit(self, generation: int) -> None:
        if generation == self._generation:
            self._session_closed = True
            self.refresh()
            if self._exit_hook is not None:
                self._exit_hook()

    @staticmethod
    def _terminal_color(value: str) -> str | None:
        if value in {"default", ""}:
            return None
        if value.startswith("#"):
            return value
        names = {
            "black": "black", "red": "red", "green": "green", "brown": "yellow",
            "blue": "blue", "magenta": "magenta", "cyan": "cyan", "white": "white",
            "brightblack": "bright_black", "brightred": "bright_red",
            "brightgreen": "bright_green", "brightyellow": "bright_yellow",
            "brightblue": "bright_blue", "brightmagenta": "bright_magenta",
            "brightcyan": "bright_cyan", "brightwhite": "bright_white",
        }
        return names.get(value, value if value.isdigit() else None)

    def _style(self, key: tuple) -> Style:
        style = self._styles.get(key)
        if style is None:
            fg, bg, bold, italic, underline, strike, reverse = key
            style = Style(
                color=self._terminal_color(fg), bgcolor=self._terminal_color(bg),
                bold=bold, italic=italic, underline=underline, strike=strike, reverse=reverse,
            )
            if len(self._styles) >= MAX_CACHED_STYLES:
                self._styles.clear()
            self._styles[key] = style
        return style

    def _scrollback_size(self) -> int:
        """How far the view can go back: until the oldest line sits under the notice row."""
        scrollback = len(getattr(self._screen, "scrollback", ()))
        if not scrollback:
            return 0
        return max(0, scrollback + self._screen.lines - (self._screen_size()[0] - 1))

    def _visible_lines(self, rows: int):
        """The lines on view and the row of the live cursor among them (None if off view)."""
        screen = self._screen
        if not self._scroll:
            cursor = screen.cursor
            return [screen.buffer[y] for y in range(rows)], (
                None if cursor.hidden else cursor.y)
        lines = [*screen.scrollback, *(screen.buffer[y] for y in range(screen.lines))]
        end = len(lines) - self._scroll
        # The first row holds the "lines back" notice, so it covers no text.
        return [None, *lines[max(0, end - (rows - 1)):end]], None

    def render(self) -> Text:
        # Selecting text re-renders on every mouse move, so this must stay cheap: append
        # each run of equally styled cells once, with a cached Style, not one per cell.
        rows, columns = self._screen_size()
        output = Text(no_wrap=True, overflow="crop")
        cursor = self._screen.cursor
        lines, cursor_y = self._visible_lines(rows)
        for y in range(rows):
            if y:
                output.append("\n")
            if y == 0 and self._scroll:
                output.append(
                    f" ↑ {self._scroll} lines back · Shift+PgDn or any key returns "[:columns],
                    style=SCROLLED_STYLE)
                continue
            if y >= len(lines) or lines[y] is None:
                continue
            line = lines[y]
            run: list[str] = []
            run_key = None
            for x in range(columns):
                cell = line[x]
                key = (
                    cell.fg, cell.bg, cell.bold, cell.italics, cell.underscore,
                    cell.strikethrough, cell.reverse or (y == cursor_y and x == cursor.x),
                )
                if key != run_key:
                    if run:
                        output.append("".join(run), style=self._style(run_key))
                    run, run_key = [], key
                run.append(cell.data)
            if run:
                output.append("".join(run), style=self._style(run_key))
        return output

    def scroll_back(self, lines: int) -> None:
        """Move the view up (positive) or down (negative) through the scrollback."""
        scroll = max(0, min(self._scroll + lines, self._scrollback_size()))
        if scroll != self._scroll:
            self._scroll = scroll
            self.refresh()

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        event.stop()
        self.scroll_back(SCROLL_STEP)

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        event.stop()
        self.scroll_back(-SCROLL_STEP)

    def on_resize(self) -> None:
        if not self.size.height:
            return
        rows, columns = self._screen_size()
        resize_screen(self._screen, rows, columns)
        if self._session and self.active:
            self._session.resize(rows, columns)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "release_focus":
            return self.active and self._escape_hook is not None
        return True

    def action_release_focus(self) -> None:
        if self._escape_hook:
            self._escape_hook()

    def on_key(self, event: Key) -> None:
        key = event.key
        if key in {"shift+pageup", "shift+pagedown"}:
            # Reading back works even after the program ended.
            event.stop()
            page = max(1, self._screen_size()[0] - 1)
            self.scroll_back(page if key == "shift+pageup" else -page)
            return
        if key == "escape" and self._escape_hook:
            # Leaving must work even after the process exited.
            event.stop()
            self._escape_hook()
            return
        if not self.active or self._session is None:
            return
        # Typing goes to the program: show where it writes, like a terminal does.
        self.scroll_back(-self._scroll)
        mapped = {
            "enter": "\r", "backspace": "\x7f", "tab": "\t", "up": "\x1b[A",
            "down": "\x1b[B", "right": "\x1b[C", "left": "\x1b[D",
            "home": "\x1b[H", "end": "\x1b[F", "delete": "\x1b[3~",
            "pageup": "\x1b[5~", "pagedown": "\x1b[6~",
        }
        if key == "escape":
            event.stop()
            if self._escape_hook:
                self._escape_hook()
            return
        if key == "ctrl+c":
            # Like desktop terminals: copy a selection, otherwise interrupt the process.
            selection = self.screen.selections.get(self)
            extracted = self.get_selection(selection) if selection is not None else None
            if extracted and extracted[0]:
                self.app.copy_to_clipboard(extracted[0])
                self.screen.clear_selection()
            else:
                self._session.write("\x03")
        elif key in mapped:
            self._session.write(mapped[key])
        elif key.startswith("ctrl+") and len(key) == 6:
            self._session.write(chr(ord(key[-1]) - 96))
        elif event.character and event.character.isprintable():
            self._session.write(event.character)
        event.stop()

    def on_paste(self, event: Paste) -> None:
        if self.active and self._session is not None:
            self._session.write(event.text[:MAX_FEED_CHARS])
            event.stop()
