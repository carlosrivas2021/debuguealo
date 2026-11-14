import re

from rich.style import Style
from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Input, Select, Static

from debugpilot.core.models import LogEntry
from debugpilot.docker.logs import LogBuffer


def entry_line(entry: LogEntry) -> str:
    """One log entry as copied text: time, stream and the original message."""
    return f"{entry.timestamp or '-'} [{entry.stream}] {entry.text}"


class LogTable(DataTable):
    """Log rows that can be dragged over with the mouse to copy whole lines.

    Textual tables have no text selection, so a drag selects rows instead: the rows it
    covers are highlighted while dragging and reported on release. A click without moving
    keeps its usual meaning.
    """

    class RowsDragged(Message):
        def __init__(self, first: int, last: int):
            super().__init__()
            self.first = first
            self.last = last

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._drag_anchor: int | None = None
        self._drag_end: int | None = None
        self._drag_moved = False

    @property
    def dragging(self) -> bool:
        return self._drag_anchor is not None

    @staticmethod
    def _row_under(event: events.MouseEvent) -> int | None:
        row = event.style.meta.get("row") if event.style else None
        return row if isinstance(row, int) and row >= 0 else None

    def _drag_range(self) -> tuple[int, int] | None:
        if self._drag_anchor is None or self._drag_end is None:
            return None
        return min(self._drag_anchor, self._drag_end), max(self._drag_anchor, self._drag_end)

    def _repaint_rows(self) -> None:
        self._clear_caches()
        self.refresh()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        row = self._row_under(event)
        if event.button != 1 or row is None:
            return
        self._drag_anchor = self._drag_end = row
        self._drag_moved = False
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag_anchor is None:
            return
        self._drag_moved = True
        row = self._row_under(event)
        if row is not None and row != self._drag_end:
            self._drag_end = row
            self._repaint_rows()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag_anchor is None:
            return
        row = self._row_under(event)
        if row is not None:
            self._drag_end = row
        selected, moved = self._drag_range(), self._drag_moved
        self._drag_anchor = self._drag_end = None
        self.release_mouse()
        self._repaint_rows()
        if moved and selected is not None:
            self.post_message(self.RowsDragged(*selected))

    def _get_row_style(self, row_index: int, base_style: Style) -> Style:
        style = super()._get_row_style(row_index, base_style)
        selected = self._drag_range()
        if selected is not None and selected[0] <= row_index <= selected[1]:
            style += self.get_component_styles("datatable--cursor").rich_style
        return style


class LogViewer(Vertical):
    """Bounded ingestion independent of rendering, visual pause and text controls."""

    DEFAULT_CSS = """
    LogViewer { height: 1fr; }
    LogViewer .log-controls { height: 3; }
    LogViewer Input { width: 1fr; }
    LogViewer Select { width: 18; }
    LogViewer Button { width: 1fr; min-width: 8; }
    LogViewer DataTable { height: 1fr; }
    LogViewer .log-status { height: 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("ctrl+space", "toggle_pause", "Pause logs"),
        Binding("ctrl+k", "clear_logs", "Clear view"),
        Binding("ctrl+y", "copy_log", "Copy entry"),
        Binding("ctrl+e", "toggle_follow", "Auto-scroll"),
        Binding("w", "toggle_wrap", "Wrap lines"),
        Binding("ctrl+f", "search", "Search"),
        Binding("n", "next_match", "Next match", show=False),
        Binding("N", "previous_match", "Previous match", show=False),
    ]

    def __init__(self, *, max_entries: int = 2000, max_bytes: int = 2 * 1024 * 1024):
        super().__init__()
        self.buffer = LogBuffer(max_entries, max_bytes)
        self.visible_entries: tuple[LogEntry, ...] = ()
        self.paused = False
        self.auto_scroll = True
        self.wrap = False
        self._dirty = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="log-controls"):
            yield Input(placeholder="Filter text", id="filter-logs")
            yield Input(placeholder="Search · Enter / N", id="search-logs")
            yield Select(
                [
                    ("All levels", ""),
                    *[
                        (level.title(), level)
                        for level in ("debug", "info", "warning", "error", "critical", "unknown")
                    ],
                ],
                value="",
                allow_blank=False,
                id="severity-logs",
            )
        yield LogTable(id="log-entries", cursor_type="row", zebra_stripes=True)
        with Horizontal(classes="log-controls"):
            yield Button("Pause", id="pause-logs")
            yield Button("Auto: on", id="follow-logs")
            yield Button("Wrap: off", id="wrap-logs")
            yield Button("Clear", id="clear-logs")
            yield Button("Copy", id="copy-log")
        yield Static("No logs yet", classes="log-status", markup=False)

    def on_mount(self) -> None:
        self._column_keys = self.query_one(DataTable).add_columns(
            "Time", "Stream", "Level", "Message"
        )
        self.set_interval(0.2, self.flush)

    def _fit_message_column(self, table: DataTable) -> None:
        """With wrap on, the message column takes the remaining width and rows grow."""
        message = table.columns[self._column_keys[-1]]
        if not self.wrap:
            message.auto_width = True
            return
        padding = 2 * table.cell_padding
        others = [
            max(len("Time"), *(len(entry.timestamp or "-") for entry in self.visible_entries)),
            max(len("Stream"), *(len(entry.stream) for entry in self.visible_entries)),
            max(len("Level"), *(len(entry.severity) for entry in self.visible_entries)),
        ] if self.visible_entries else [len("Time"), len("Stream"), len("Level")]
        room = table.scrollable_content_region.width - sum(width + padding for width in others)
        message.auto_width = False
        message.width = max(10, room - padding)

    def append(self, entry: LogEntry) -> None:
        self.buffer.append(entry)
        self._dirty = True

    def flush(self) -> None:
        table = self.query_one(LogTable)
        # A drag maps rows to entries; rebuilding the rows under the mouse would shift it.
        if not self._dirty or self.paused or table.dragging:
            return
        # Preserve the user's viewport when auto-scroll is off.
        row, scroll_y = table.cursor_row, table.scroll_y
        self.visible_entries = self.buffer.entries(
            text=self.query_one("#filter-logs", Input).value,
            severity=str(self.query_one(Select).value),
        )
        query = self.query_one("#search-logs", Input).value.casefold()
        table.clear()
        self._fit_message_column(table)
        for entry in self.visible_entries:
            text = Text(entry.text.replace("\r", " ").replace("\n", " ↵ "))
            if query:
                text.highlight_regex(re.compile(re.escape(query), re.IGNORECASE), "bold reverse")
            if entry.truncated:
                text.append(" [truncated]", style="dim")
            table.add_row(
                Text(entry.timestamp or "-"), entry.stream, entry.severity, text,
                height=None if self.wrap else 1,
            )
        if table.row_count:
            table.move_cursor(
                row=table.row_count - 1 if self.auto_scroll else row, scroll=self.auto_scroll
            )
            if not self.auto_scroll:
                table.scroll_to(y=scroll_y, animate=False)
        self._dirty = False
        self._update_status()

    def _search_query(self) -> str:
        return self.query_one("#search-logs", Input).value.casefold()

    def _match_rows(self) -> list[int]:
        query = self._search_query()
        if not query:
            return []
        return [
            row for row, entry in enumerate(self.visible_entries) if query in entry.text.casefold()
        ]

    def _update_status(self) -> None:
        status = f"{len(self.visible_entries)} shown / {len(self.buffer.entries())} retained"
        if self._search_query():
            matches = self._match_rows()
            row = self.query_one(DataTable).cursor_row
            if not matches:
                status += " · No matches"
            elif row in matches:
                status += f" · Match {matches.index(row) + 1}/{len(matches)}"
            else:
                status += f" · {len(matches)} match{'' if len(matches) == 1 else 'es'}"
        self.query_one(".log-status", Static).update(
            f"{status} · Copy uses terminal clipboard support"
        )

    @on(DataTable.RowHighlighted, "#log-entries")
    def row_highlighted(self) -> None:
        if not self.paused:
            self._update_status()

    @on(Input.Changed, "#filter-logs")
    @on(Select.Changed, "#severity-logs")
    def filters_changed(self) -> None:
        self._dirty = True
        self.flush()

    @on(Input.Changed, "#search-logs")
    def search_changed(self) -> None:
        self._dirty = True
        self.flush()
        self.action_next_match(start=0)

    @on(Input.Submitted, "#search-logs")
    def search_submitted(self) -> None:
        self.action_next_match()

    def action_search(self) -> None:
        self.query_one("#search-logs", Input).focus()

    def action_next_match(self, start: int | None = None) -> None:
        matches = self._match_rows()
        if not matches:
            return
        current = self.query_one(DataTable).cursor_row
        start = current + 1 if start is None else start
        self._jump_to(next((row for row in matches if row >= start), matches[0]))

    def action_previous_match(self) -> None:
        matches = self._match_rows()
        if not matches:
            return
        current = self.query_one(DataTable).cursor_row
        self._jump_to(next((row for row in reversed(matches) if row < current), matches[-1]))

    def _jump_to(self, row: int) -> None:
        self.auto_scroll = False
        self.query_one("#follow-logs", Button).label = "Auto: off"
        self.query_one(DataTable).move_cursor(row=row)
        self._update_status()

    @on(Button.Pressed, "#pause-logs")
    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        self.query_one("#pause-logs", Button).label = "Resume" if self.paused else "Pause"
        self.query_one(".log-status", Static).update(
            "Paused visually; bounded ingestion continues" if self.paused else "Resumed"
        )
        self.flush()

    @on(Button.Pressed, "#follow-logs")
    def action_toggle_follow(self) -> None:
        self.auto_scroll = not self.auto_scroll
        self.query_one(
            "#follow-logs", Button
        ).label = f"Auto: {'on' if self.auto_scroll else 'off'}"
        if self.auto_scroll:
            self.query_one(DataTable).move_cursor(row=max(0, len(self.visible_entries) - 1))

    @on(Button.Pressed, "#wrap-logs")
    def action_toggle_wrap(self) -> None:
        self.wrap = not self.wrap
        self.query_one("#wrap-logs", Button).label = f"Wrap: {'on' if self.wrap else 'off'}"
        self._dirty = True
        self.flush()

    def on_resize(self) -> None:
        if self.wrap:
            self._dirty = True
            self.call_after_refresh(self.flush)

    @on(LogTable.RowsDragged)
    def rows_dragged(self, event: LogTable.RowsDragged) -> None:
        entries = self.visible_entries[event.first:event.last + 1]
        if not entries:
            return
        self.app.copy_to_clipboard("\n".join(entry_line(entry) for entry in entries))
        noun = "line" if len(entries) == 1 else "lines"
        self.notify(f"Copied {len(entries)} {noun}", timeout=2)

    @on(Button.Pressed, "#clear-logs")
    def action_clear_logs(self) -> None:
        self.buffer.clear()
        self.visible_entries = ()
        self.query_one(DataTable).clear()
        self._dirty = True
        if not self.paused:
            self.flush()

    @on(Button.Pressed, "#copy-log")
    def action_copy_log(self) -> None:
        row = self.query_one(DataTable).cursor_row
        if self.visible_entries:
            entry = self.visible_entries[row]
            self.app.copy_to_clipboard(entry_line(entry))
            self.notify("Entry copied via terminal clipboard; terminal support is required.")
