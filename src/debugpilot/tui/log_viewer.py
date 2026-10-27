import re

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Select, Static

from debugpilot.core.models import LogEntry
from debugpilot.docker.logs import LogBuffer


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
        Binding("ctrl+f", "search", "Search"),
        Binding("n", "next_match", "Next match", show=False),
    ]

    def __init__(self, *, max_entries: int = 2000, max_bytes: int = 2 * 1024 * 1024):
        super().__init__()
        self.buffer = LogBuffer(max_entries, max_bytes)
        self.visible_entries: tuple[LogEntry, ...] = ()
        self.paused = False
        self.auto_scroll = True
        self._dirty = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="log-controls"):
            yield Input(placeholder="Filter text", id="filter-logs")
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
        with Horizontal(classes="log-controls"):
            yield Input(placeholder="Search (Enter / N: next)", id="search-logs")
        yield DataTable(id="log-entries", cursor_type="row", zebra_stripes=True)
        with Horizontal(classes="log-controls"):
            yield Button("Pause", id="pause-logs")
            yield Button("Auto: on", id="follow-logs")
            yield Button("Clear", id="clear-logs")
            yield Button("Copy", id="copy-log")
        yield Static("No logs yet", classes="log-status", markup=False)

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Time", "Stream", "Level", "Message")
        self.set_interval(0.2, self.flush)

    def append(self, entry: LogEntry) -> None:
        self.buffer.append(entry)
        self._dirty = True

    def flush(self) -> None:
        if not self._dirty or self.paused:
            return
        table = self.query_one(DataTable)
        # Preserve the user's viewport when auto-scroll is off.
        row, scroll_y = table.cursor_row, table.scroll_y
        self.visible_entries = self.buffer.entries(
            text=self.query_one("#filter-logs", Input).value,
            severity=str(self.query_one(Select).value),
        )
        query = self.query_one("#search-logs", Input).value.casefold()
        table.clear()
        for entry in self.visible_entries:
            text = Text(entry.text.replace("\r", " ").replace("\n", " ↵ "))
            if query:
                text.highlight_regex(re.compile(re.escape(query), re.IGNORECASE), "bold reverse")
            if entry.truncated:
                text.append(" [truncated]", style="dim")
            table.add_row(Text(entry.timestamp or "-"), entry.stream, entry.severity, text)
        if table.row_count:
            table.move_cursor(
                row=table.row_count - 1 if self.auto_scroll else row, scroll=self.auto_scroll
            )
            if not self.auto_scroll:
                table.scroll_to(y=scroll_y, animate=False)
        self.query_one(".log-status", Static).update(
            f"{len(self.visible_entries)} shown / {len(self.buffer.entries())} retained"
            " · Copy uses terminal clipboard support"
        )
        self._dirty = False

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
        query = self.query_one("#search-logs", Input).value.casefold()
        if not query or not self.visible_entries:
            return
        table = self.query_one(DataTable)
        start = table.cursor_row + 1 if start is None else start
        for offset in range(len(self.visible_entries)):
            row = (start + offset) % len(self.visible_entries)
            if query in self.visible_entries[row].text.casefold():
                self.auto_scroll = False
                self.query_one("#follow-logs", Button).label = "Auto: off"
                table.move_cursor(row=row)
                break

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
            self.app.copy_to_clipboard(f"{entry.timestamp or '-'} [{entry.stream}] {entry.text}")
            self.notify("Entry copied via terminal clipboard; terminal support is required.")
