"""A watch with fields expands like a variable; C copies it and its value previews below."""

from test_code_debug_ui import debug_app, mark
from test_expand_variables_ui import NESTED
from test_tui_grouping import until
from test_watch_ui import add_watch, watch_rows

from debugpilot.tui.code_debug import WatchTable


def preview(app):
    widget = app.query_one('#watch-preview')
    return str(widget.render()) if widget.display else ''


async def watch_config(pilot, app, roots):
    (roots[0] / 'main.py').write_text(NESTED, encoding='utf-8')
    await pilot.click('#area-code')
    await mark(pilot, app, line=3)
    await pilot.press('shift+f5')
    await until(pilot, lambda: 'config' in app.query_one('#code-variables').text)
    await add_watch(pilot, app, 'config')
    await add_watch(pilot, app, "config['port'] + 1")
    await until(pilot, lambda: watch_rows(app) == [
        ('▸ config', "{'port': 80, 'point': {'x': 1}}"), ("config['port'] + 1", '81')])
    table = app.query_one('#code-watches', WatchTable)
    table.focus()
    table.move_cursor(row=0)
    await pilot.pause()
    return table


async def test_right_and_left_expand_and_collapse_a_watch(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await watch_config(pilot, app, roots)
        await pilot.press('right')
        await until(pilot, lambda: ("    'port'", '80') in watch_rows(app))
        assert watch_rows(app)[0][0] == '▾ config'
        assert watch_rows(app)[-1] == ("config['port'] + 1", '81')  # The next watch follows.
        table.move_cursor(row=[row[0] for row in watch_rows(app)].index("  ▸ 'point'"))
        await pilot.press('space')
        await until(pilot, lambda: ("      'x'", '1') in watch_rows(app))
        await pilot.press('left')  # Closes 'point'.
        await until(pilot, lambda: ("      'x'", '1') not in watch_rows(app))
        await pilot.press('left')  # On a closed field: back to its watch.
        await pilot.pause()
        assert table.cursor_row == 0
        await pilot.press('left')
        await until(pilot, lambda: len(watch_rows(app)) == 2)


async def test_delete_removes_only_whole_watches(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await watch_config(pilot, app, roots)
        await pilot.press('right')
        await until(pilot, lambda: ("    'port'", '80') in watch_rows(app))
        table.move_cursor(row=[row[0] for row in watch_rows(app)].index("    'port'"))
        await pilot.press('delete')  # A field is not a watch: nothing goes.
        await pilot.pause(0.2)
        assert ("    'port'", '80') in watch_rows(app)
        table.move_cursor(row=0)
        await pilot.press('delete')
        await until(pilot, lambda: watch_rows(app) == [("config['port'] + 1", '81')])


async def test_c_copies_a_watch_and_its_value_shows_below(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    copied = []
    async with app.run_test(size=(140, 52)) as pilot:
        monkeypatch.setattr(app, 'copy_to_clipboard', copied.append)
        await watch_config(pilot, app, roots)
        await until(pilot, lambda: preview(app) == "config = {'port': 80, 'point': {'x': 1}}")
        await pilot.press('c')
        await until(pilot, lambda: copied == ["{'port': 80, 'point': {'x': 1}}"])
