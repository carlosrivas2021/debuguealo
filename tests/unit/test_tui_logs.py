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


class WideLogApp(App):
    def compose(self) -> ComposeResult:
        yield LogViewer(max_entries=50, max_bytes=64 * 1024)


def _messages(app):
    return [item.message for item in app._notifications]


async def _filled(pilot, app, texts):
    viewer = app.query_one(LogViewer)
    for text in texts:
        viewer.append(LogEntry(text=text, stream="stdout", timestamp="10:00:00"))
    viewer.flush()
    await pilot.pause()
    return viewer, viewer.query_one(DataTable)


async def test_dragging_over_rows_copies_those_lines(monkeypatch):
    app = WideLogApp()
    copied = []
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    async with app.run_test(size=(120, 30)) as pilot:
        await _filled(pilot, app, ["zero", "one", "two", "three"])
        # Row 0 is drawn on line 1, under the column header.
        await pilot.mouse_down("#log-entries", offset=(30, 2))
        await pilot.hover("#log-entries", offset=(32, 3))
        await pilot.hover("#log-entries", offset=(34, 4))
        await pilot.mouse_up("#log-entries", offset=(34, 4))
        await pilot.pause()

        assert copied == ["10:00:00 [stdout] one\n10:00:00 [stdout] two\n10:00:00 [stdout] three"]
        assert "Copied 3 lines" in _messages(app)


async def test_dragging_upwards_copies_in_log_order(monkeypatch):
    app = WideLogApp()
    copied = []
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    async with app.run_test(size=(120, 30)) as pilot:
        await _filled(pilot, app, ["zero", "one", "two"])
        await pilot.mouse_down("#log-entries", offset=(30, 3))
        await pilot.hover("#log-entries", offset=(30, 1))
        await pilot.mouse_up("#log-entries", offset=(30, 1))
        await pilot.pause()

        assert copied == ["10:00:00 [stdout] zero\n10:00:00 [stdout] one\n10:00:00 [stdout] two"]


async def test_dragging_within_one_row_copies_that_line_and_a_click_copies_nothing(monkeypatch):
    app = WideLogApp()
    copied = []
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    async with app.run_test(size=(120, 30)) as pilot:
        await _filled(pilot, app, ["zero", "one"])
        await pilot.click("#log-entries", offset=(30, 2))
        await pilot.pause()
        assert copied == []

        await pilot.mouse_down("#log-entries", offset=(30, 2))
        await pilot.hover("#log-entries", offset=(40, 2))
        await pilot.mouse_up("#log-entries", offset=(40, 2))
        await pilot.pause()
        assert copied == ["10:00:00 [stdout] one"]
        assert "Copied 1 line" in _messages(app)


async def test_new_logs_do_not_shift_rows_during_a_drag(monkeypatch):
    app = WideLogApp()
    copied = []
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    async with app.run_test(size=(120, 30)) as pilot:
        viewer, table = await _filled(pilot, app, ["zero", "one", "two"])
        await pilot.mouse_down("#log-entries", offset=(30, 1))
        viewer.append(LogEntry(text="late", stream="stdout", timestamp="10:00:01"))
        viewer.flush()
        assert table.row_count == 3
        await pilot.hover("#log-entries", offset=(30, 2))
        await pilot.mouse_up("#log-entries", offset=(30, 2))
        await pilot.pause()

        assert copied == ["10:00:00 [stdout] zero\n10:00:00 [stdout] one"]
        await pilot.pause(0.3)
        assert table.row_count == 4


async def test_wrap_shows_long_messages_on_several_lines():
    app = WideLogApp()
    async with app.run_test(size=(100, 30)) as pilot:
        long_text = " ".join(f"word{n}" for n in range(60))
        viewer, table = await _filled(pilot, app, ["short", long_text])
        assert [row.height for row in table.ordered_rows] == [1, 1]

        await pilot.click("#wrap-logs")
        await pilot.pause()

        assert str(app.query_one("#wrap-logs").label) == "Wrap: on"
        heights = [row.height for row in table.ordered_rows]
        assert heights[0] == 1 and heights[1] > 1
        # Nothing runs past the right edge: the table never scrolls sideways.
        assert table.virtual_size.width <= table.scrollable_content_region.width

        await pilot.pause(0.4)  # Let Textual's button active effect finish before clicking again.
        await pilot.click("#wrap-logs")
        await pilot.pause()
        assert [row.height for row in table.ordered_rows] == [1, 1]


async def test_w_toggles_wrap_and_wrapped_rows_follow_the_width():
    app = WideLogApp()
    async with app.run_test(size=(100, 30)) as pilot:
        long_text = " ".join(f"word{n}" for n in range(60))
        viewer, table = await _filled(pilot, app, [long_text])
        table.focus()
        await pilot.press("w")
        await pilot.pause()
        assert viewer.wrap
        narrow = table.ordered_rows[0].height

        await pilot.resize_terminal(160, 30)
        await pilot.pause(0.3)
        assert table.ordered_rows[0].height < narrow
        assert table.virtual_size.width <= table.scrollable_content_region.width


async def test_typing_w_in_the_filter_and_search_fields_types_it():
    app = WideLogApp()
    async with app.run_test(size=(100, 30)) as pilot:
        viewer, _ = await _filled(pilot, app, ["warning one"])
        for selector in ("#filter-logs", "#search-logs"):
            field = viewer.query_one(selector, Input)
            field.focus()
            await pilot.press("w")
            assert field.value == "w"
            field.value = ""
        assert not viewer.wrap
