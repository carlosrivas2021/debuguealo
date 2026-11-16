"""The highlighted variable's whole value shows under the Variables pane, and C copies it."""

from test_code_debug_ui import debug_app, mark
from test_expand_variables_ui import row_of
from test_tui_grouping import until

from debugpilot.tui.code_debug import VariablesTable

PROGRAM = (
    "config = {'port': 80, 'point': {'x': 1}}\n"
    "note = 'word ' * 100 + 'END'\n"
    "deep = {'items': [{'sku': 'book'}]}\n"
    'ready = True\n'
    'print("RESULT")\n'
)


def preview(app):
    widget = app.query_one('#variable-preview')
    return str(widget.render()) if widget.display else ''


async def pause(pilot, app, roots):
    (roots[0] / 'main.py').write_text(PROGRAM, encoding='utf-8')
    await pilot.click('#area-code')
    await mark(pilot, app, line=5)
    await pilot.press('shift+f5')
    table = app.query_one('#code-variables', VariablesTable)
    await until(pilot, lambda: any(row.name == 'note' for row in table.variable_rows))
    table.focus()
    return table


async def test_the_whole_value_of_the_highlighted_variable_shows_below(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await pause(pilot, app, roots)
        table.move_cursor(row=row_of(table, 'note'))
        await until(pilot, lambda: 'END' in preview(app))
        # The row shows a cut value; the preview shows all of it.
        assert 'END' not in table.text
        assert preview(app).startswith("note = 'word word")
        assert preview(app).count('word') == 100
        table.move_cursor(row=row_of(table, 'config'))
        await until(pilot, lambda: preview(app) == "config = {'port': 80, 'point': {'x': 1}}")
        table.move_cursor(row=0)  # A scope heading has no value.
        await until(pilot, lambda: preview(app) == '')


async def test_c_copies_the_highlighted_value(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    copied = []
    async with app.run_test(size=(140, 52)) as pilot:
        monkeypatch.setattr(app, 'copy_to_clipboard', copied.append)
        table = await pause(pilot, app, roots)
        table.move_cursor(row=row_of(table, 'deep'))
        await pilot.pause()
        assert '[{...}]' in table.text  # debugpy shortens the nested dict...
        await pilot.press('c')
        # ...but the copy is Python's whole repr.
        await until(pilot, lambda: copied == ["{'items': [{'sku': 'book'}]}"])
        assert app.focused is table  # C never opens the container shell from here.


async def test_long_values_never_add_a_horizontal_scrollbar(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await pause(pilot, app, roots)
        await pilot.pause()
        assert table.virtual_size.width > table.content_region.width  # A row is too wide.
        assert not table.show_horizontal_scrollbar


async def test_the_highlighted_row_stays_visible_above_the_preview(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 34)) as pilot:  # Short: the rows need scrolling.
        table = await pause(pilot, app, roots)
        # The last `note` (in Globals): its long value makes the preview grow under it.
        target = max(index for index, row in enumerate(table.variable_rows)
                     if row.name == 'note')
        while table.cursor_row < target:
            await pilot.press('down')  # Down the list, as a user would.
        await until(pilot, lambda: 'END' in preview(app))
        await pilot.pause(0.2)
        top = int(table.scroll_y)
        assert table.virtual_size.height > table.content_region.height  # It does scroll.
        assert top <= table.cursor_row < top + table.content_region.height
