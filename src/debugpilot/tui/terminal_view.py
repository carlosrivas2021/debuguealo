from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pyte
from rich.style import Style
from rich.text import Text
from textual.events import Key, Paste
from textual.widget import Widget

from debugpilot.core.models import ContainerInfo
from debugpilot.terminal import TerminalSession

SCREEN_ROWS = 200
SCREEN_COLUMNS = 500
MAX_FEED_CHARS = 64 * 1024


@dataclass(frozen=True)
class TerminalContext:
    kind: str
    cwd: Path
    container: ContainerInfo | None = None
    endpoint: str | None = None


class TerminalPane(Widget):
    """Native PTY display/input widget. Construction and mount never start a shell."""

    can_focus = True

    def __init__(self, *, escape_hook=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._escape_hook = escape_hook
        self._session: TerminalSession | None = None
        self._terminal_context: TerminalContext | None = None
        self._screen = pyte.Screen(80, 24)
        self._stream = pyte.Stream(self._screen)
        # Textual owns MessagePump._closed; session state must not stop its event loop.
        self._session_closed = True
        self._generation = 0

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
        rows, columns = self._screen_size()
        self._screen = pyte.Screen(columns=columns, lines=rows)
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

    def _accept_output(self, generation: int, text: str) -> None:
        if self._session_closed or generation != self._generation:
            return
        self._stream.feed(text[:MAX_FEED_CHARS])
        self.refresh()

    def _accept_exit(self, generation: int) -> None:
        if generation == self._generation:
            self._session_closed = True
            self.refresh()

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

    def render(self) -> Text:
        rows, columns = self._screen_size()
        output = Text(no_wrap=True, overflow="crop")
        cursor = self._screen.cursor
        for y in range(rows):
            if y:
                output.append("\n")
            for x in range(columns):
                cell = self._screen.buffer[y][x]
                style = Style(
                    color=self._terminal_color(cell.fg),
                    bgcolor=self._terminal_color(cell.bg),
                    bold=cell.bold,
                    italic=cell.italics,
                    underline=cell.underscore,
                    strike=cell.strikethrough,
                    reverse=cell.reverse or (not cursor.hidden and cursor.x == x and cursor.y == y),
                )
                output.append(cell.data, style=style)
        return output

    def on_resize(self) -> None:
        rows, columns = self._screen_size()
        self._screen.resize(lines=rows, columns=columns)
        if self._session and self.active:
            self._session.resize(rows, columns)

    def on_key(self, event: Key) -> None:
        if not self.active or self._session is None:
            return
        key = event.key
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
