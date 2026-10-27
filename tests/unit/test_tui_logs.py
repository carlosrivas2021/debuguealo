from textual.app import App, ComposeResult
from textual.widgets import DataTable, Input, Select

from debugpilot.core.models import LogEntry
from debugpilot.tui.log_viewer import LogViewer


class LogApp(App):
    def compose(self) -> ComposeResult:
        yield LogViewer(max_entries=3, max_bytes=1024)


async def test_log_controls_keep_ingestion_bounded_while_paused():
    app = LogApp()
    async with app.run_test(size=(120, 30)) as pilot:
        viewer = app.query_one(LogViewer)
        viewer.append(LogEntry(text="first"))
        viewer.flush()
        table = viewer.query_one(DataTable)
        assert table.row_count == 1
        await pilot.click("#pause-logs")
        for number in range(6):
            viewer.append(LogEntry(text=f"line {number}"))
        viewer.flush()
        assert table.row_count == 1
        assert [item.text for item in viewer.buffer.entries()] == ["line 3", "line 4", "line 5"]
        await pilot.pause(0.4)  # Let Textual's button active effect finish before clicking again.
        await pilot.click("#pause-logs")
        assert table.row_count == 3
        assert viewer.visible_entries[-1].text == "line 5"
        await pilot.click("#clear-logs")
        assert not viewer.buffer.entries() and table.row_count == 0


async def test_filter_search_and_copy_use_plain_bounded_records(monkeypatch):
    app = LogApp()
    copied = []
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    async with app.run_test(size=(120, 30)) as pilot:
        viewer = app.query_one(LogViewer)
        for text, severity in [("INFO good", "info"), ("ERROR [red]bad", "error")]:
            viewer.append(LogEntry(text=text, severity=severity, stream="stderr"))
        viewer.flush()
        viewer.query_one("#filter-logs", Input).value = "BAD"
        await pilot.pause()
        assert [item.text for item in viewer.visible_entries] == ["ERROR [red]bad"]
        viewer.query_one("#severity-logs", Select).value = "info"
        await pilot.pause()
        assert viewer.query_one(DataTable).row_count == 0
        viewer.query_one("#filter-logs", Input).value = ""
        viewer.query_one("#severity-logs", Select).value = ""
        viewer.query_one("#search-logs", Input).value = "bad"
        await pilot.pause()
        assert viewer.query_one(DataTable).cursor_row == 1
        await pilot.click("#copy-log")
        assert len(copied) == 1 and "[stderr] ERROR [red]bad" in copied[0]


async def test_manual_scroll_and_small_terminal_controls():
    app = LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        viewer = app.query_one(LogViewer)
        for number in range(3):
            viewer.append(LogEntry(text=str(number)))
        viewer.flush()
        await pilot.click("#follow-logs")
        table = viewer.query_one(DataTable)
        table.move_cursor(row=0)
        viewer.append(LogEntry(text="new"))
        viewer.flush()
        assert not viewer.auto_scroll and table.cursor_row == 0
        assert viewer.buffer.byte_size <= 1024
        for selector in ("#pause-logs", "#clear-logs", "#copy-log", "#follow-logs"):
            assert app.query_one(selector).region.width > 0
