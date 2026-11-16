"""The selected project's breakpoints in one list: open, switch off, remove."""

from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Click
from textual.message import Message
from textual.widgets import DataTable, Static

# A row's location: the stored (root, file) key and the line.
Location = tuple[tuple[Path, Path], int]
EXECUTION_STYLE = Style(color="#facc15", bold=True)
MUTED_STYLE = Style(color="#7f8c93")
WARNING_STYLE = Style(color="#e5c07b")


class BreakpointsTitle(Horizontal, can_focus=True):
    """The section title, laid out like PROFILES: name on the left, count on the right.

    Click, Enter or Space opens or closes the list.
    """

    BINDINGS = [
        Binding("enter", "toggle", "Open/close", show=False),
        Binding("space", "toggle", "Open/close"),
    ]

    class Toggle(Message):
        def __init__(self, from_keyboard: bool):
            super().__init__()
            # From the keyboard, opening also moves into the list to pick a breakpoint.
            self.from_keyboard = from_keyboard

    def compose(self) -> ComposeResult:
        yield Static("BREAKPOINTS", id="source-breakpoints-name")
        yield Static("", id="source-breakpoints-count", markup=False)

    def show(self, count: str) -> None:
        self.query_one("#source-breakpoints-count", Static).update(count)

    @property
    def text(self) -> str:
        """The title as shown, name and count, for tests and screen readers."""
        count = self.query_one("#source-breakpoints-count", Static).render()
        return f"BREAKPOINTS {count}".rstrip()

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Toggle(False))

    def action_toggle(self) -> None:
        self.post_message(self.Toggle(True))


class BreakpointList(DataTable):
    """Enter opens the line; Space switches it on or off; Delete removes it; A does all."""

    BINDINGS = [
        Binding("space", "toggle", "On/off"),
        Binding("delete", "remove", "Remove"),
        Binding("a", "toggle_all", "All on/off"),
    ]

    class Toggle(Message):
        def __init__(self, location: Location):
            super().__init__()
            self.location = location

    class Remove(Message):
        def __init__(self, location: Location):
            super().__init__()
            self.location = location

    class ToggleAll(Message):
        pass

    def __init__(self, **kwargs):
        # Same look as the profiles list above it.
        super().__init__(cursor_type="row", show_header=False, zebra_stripes=True,
                         cell_padding=0, **kwargs)
        self._locations: list[Location] = []

    def on_mount(self) -> None:
        # One cell per row: the sidebar is narrow, and long details are clipped, not scrolled.
        self.add_column("Breakpoint")

    def show(self, rows) -> None:
        """rows: (location, glyph, style, label, detail, note, off, executing), in order.

        The note is the debugger's answer worth a look: unverified, or moved to another line.
        """
        current = self.location
        self.clear()
        self._locations = []
        for location, glyph, style, label, detail, note, off, executing in rows:
            text = Text(no_wrap=True, overflow="crop")
            text.append("▶" if executing else " ", EXECUTION_STYLE)
            text.append(glyph, style)
            text.append(f" {label}", MUTED_STYLE if off else Style())
            if detail:
                text.append(f" {detail}", MUTED_STYLE)
            if off:
                text.append(" (off)", MUTED_STYLE)
            elif note:
                text.append(f" {note}", WARNING_STYLE)
            self.add_row(text)
            self._locations.append(location)
        if current in self._locations:
            self.move_cursor(row=self._locations.index(current), animate=False)

    @property
    def location(self) -> Location | None:
        if not self._locations or not 0 <= self.cursor_row < len(self._locations):
            return None
        return self._locations[self.cursor_row]

    def location_at(self, row: int) -> Location | None:
        return self._locations[row] if 0 <= row < len(self._locations) else None

    def action_toggle(self) -> None:
        if self.location is not None:
            self.post_message(self.Toggle(self.location))

    def action_remove(self) -> None:
        if self.location is not None:
            self.post_message(self.Remove(self.location))

    def action_toggle_all(self) -> None:
        if self._locations:
            self.post_message(self.ToggleAll())
