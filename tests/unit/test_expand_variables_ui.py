"""Right/Left expand and collapse nested variables in the Variables pane."""

from test_code_debug_ui import debug_app, mark
from test_edit_variable_ui import output
from test_tui_grouping import until
from textual.widgets import Input

from debugpilot.tui.code_debug import VariablesTable

NESTED = (
    "config = {'port': 80, 'point': {'x': 1}}\n"
    'ready = True\n'
    "print(f\"RESULT:{config['port']}:{config['point']['x']}\")\n"
)


def lines(table):
    return table.text.splitlines()


def row_of(table, name):
    return next(index for index, variable in enumerate(table.variable_rows)
                if variable.name == name)


async def pause_on_config(pilot, app, roots):
    (roots[0] / 'main.py').write_text(NESTED, encoding='utf-8')
    await pilot.click('#area-code')
    await mark(pilot, app, line=3)
    await pilot.press('shift+f5')
    table = app.query_one('#code-variables', VariablesTable)
    await until(pilot, lambda: any(line.startswith('▸ config = ') for line in lines(table)))
    table.focus()
    table.move_cursor(row=row_of(table, 'config'))
    await pilot.pause()
    return table


async def test_right_expands_and_left_collapses_a_nested_variable(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await pause_on_config(pilot, app, roots)
        await pilot.press('right')
        await until(pilot, lambda: "    'port' = 80" in lines(table))
        assert any(line.startswith('▾ config = ') for line in lines(table))
        assert any(line.startswith("  ▸ 'point' = ") for line in lines(table))
        assert table.cursor_row == row_of(table, 'config')  # The cursor stays put.

        table.move_cursor(row=row_of(table, "'point'"))
        await pilot.press('right')
        await until(pilot, lambda: "      'x' = 1" in lines(table))

        table.move_cursor(row=row_of(table, "'x'"))
        await pilot.press('left')  # On a field: go to the variable that holds it.
        await pilot.pause()
        assert table.cursor_row == row_of(table, "'point'")
        await pilot.press('left')  # On an expanded variable: collapse it.
        await until(pilot, lambda: "      'x' = 1" not in lines(table))
        assert "    'port' = 80" in lines(table)


async def test_an_expanded_field_is_edited_and_stays_expanded(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await pause_on_config(pilot, app, roots)
        await pilot.press('right')
        await until(pilot, lambda: "    'port' = 80" in lines(table))
        table.move_cursor(row=row_of(table, "'port'"))
        await pilot.pause()
        await pilot.press('enter')
        field = app.screen.query_one('#variable-value', Input)
        await until(pilot, lambda: field.has_focus)
        assert field.value == '80'
        # It sits after the indented "'port' = ".
        assert field.region.x > table.content_region.x + len("    'port' = ") - 1
        field.value = '8080'
        await pilot.press('enter')
        await until(pilot, lambda: "    'port' = 8080" in lines(table))
        await pilot.press('f5')
        await until(pilot, lambda: 'RESULT:8080:1' in output(app))


async def test_a_plain_variable_does_not_expand(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await pause_on_config(pilot, app, roots)
        before = lines(table)
        for row in (row_of(table, 'ready'), 0):  # A boolean, then the scope heading.
            table.move_cursor(row=row)
            await pilot.press('right')
            await pilot.pause(0.3)
            assert lines(table) == before


async def test_space_toggles_a_nested_variable_like_the_file_tree(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await pause_on_config(pilot, app, roots)
        await pilot.press('space')
        await until(pilot, lambda: "    'port' = 80" in lines(table))
        assert not app.query_one('#variable-value').display  # Space never edits.
        await pilot.press('space')
        await until(pilot, lambda: "    'port' = 80" not in lines(table))
        assert any(line.startswith('▸ config = ') for line in lines(table))
