"""A one-row handle between two stacked panes that resizes them by dragging."""

from rich.text import Text
from textual.events import MouseDown, MouseMove, MouseUp
from textual.message import Message
from textual.widgets import Static


class PaneSplitter(Static):
    """Drag up or down to move the boundary; reports each row it moves."""

    # Dragging must move the boundary, not select the handle's characters.
    ALLOW_SELECT = False
    DEFAULT_CSS = """
    PaneSplitter { height: 1; color: #3a454c; }
    PaneSplitter:hover { color: #7f8c93; }
    """

    class Moved(Message):
        def __init__(self, rows: int):
            super().__init__()
            self.rows = rows

    def __init__(self, **kwargs):
        super().__init__("", markup=False, **kwargs)
        self._last_y: int | None = None

    def render(self) -> Text:
        # A gray rule across the pane with a grip in the middle.
        width = max(1, self.size.width)
        middle = width // 2
        return Text("─" * middle + "⇕" + "─" * (width - middle - 1))

    def on_mouse_down(self, event: MouseDown) -> None:
        self.capture_mouse()
        self._last_y = event.screen_y
        event.stop()

    def on_mouse_move(self, event: MouseMove) -> None:
        if self._last_y is None:
            return
        rows = event.screen_y - self._last_y
        if rows:
            self._last_y = event.screen_y
            self.post_message(self.Moved(rows))

    def on_mouse_up(self, event: MouseUp) -> None:
        self._last_y = None
        self.release_mouse()
        event.stop()
