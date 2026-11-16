"""Enter on a paused variable edits its value from the Variables pane."""

from test_code_debug_ui import debug_app, mark, rendered
from test_tui_grouping import until
from textual.widgets import Input, RichLog

from debugpilot.tui.code_debug import VariablesTable


def output(app):
    return '\n'.join(str(line.text) for line in app.query_one('#code-debug-output', RichLog).lines)


async def pause_on_answer(pilot, app):
    await pilot.click('#area-code')
    await mark(pilot, app)  # Line 4: answer = increment(answer), with answer = 41.
    await pilot.press('shift+f5')
    await until(pilot, lambda: 'answer = 41' in rendered(app, '#code-variables'))
    table = app.query_one('#code-variables', VariablesTable)
    table.focus()
    row = next(index for index, variable in enumerate(table.variable_rows)
               if variable.name == 'answer')
    table.move_cursor(row=row)
    await pilot.pause()
    return table


async def test_enter_on_a_variable_sets_the_value_the_program_uses(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await pause_on_answer(pilot, app)
        await pilot.press('enter')
        field = app.screen.query_one('#variable-value', Input)
        await until(pilot, lambda: field.has_focus)
        assert field.value == '41'  # Prefilled with the current value.
        # It sits on the variable's own row, after "answer = ".
        assert field.region.y == table.content_region.y + table.cursor_row
        assert field.region.x > table.content_region.x
        field.value = '99'
        await pilot.press('enter')
        await until(pilot, lambda: 'answer = 99' in rendered(app, '#code-variables'))
        assert table.has_focus
        await pilot.press('f5')
        await until(pilot, lambda: 'RESULT:100' in output(app))


async def test_esc_and_an_invalid_value_change_nothing(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    notices = []
    async with app.run_test(size=(140, 52)) as pilot:
        monkeypatch.setattr(app, 'notify', lambda message, **_kw: notices.append(message))
        table = await pause_on_answer(pilot, app)
        await pilot.press('enter')
        await until(pilot, lambda: app.query_one('#variable-value').display)
        await pilot.press('escape')
        await until(pilot, lambda: table.has_focus)
        assert not app.query_one('#variable-value').display
        await pilot.press('enter')
        field = app.screen.query_one('#variable-value', Input)
        await until(pilot, lambda: field.has_focus)
        field.value = 'missing_name'
        await pilot.press('enter')
        await until(pilot, lambda: any('missing_name' in notice for notice in notices))
        assert 'answer = 41' in rendered(app, '#code-variables')


async def test_a_scope_heading_is_not_editable(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await pause_on_answer(pilot, app)
        table.move_cursor(row=0)  # The scope heading.
        await pilot.pause()
        await pilot.press('enter')
        await pilot.pause(0.2)
        assert not app.query_one('#variable-value').display


async def test_alt_arrows_reach_the_debug_panes_while_debugging(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pause_on_answer(pilot, app)
        app.query_one('#code-projects').focus()
        visited = []
        for _ in range(8):
            await pilot.press('alt+right')
            await pilot.pause()
            visited.append(app.focused.id)
        # The breakpoints title joins once the project has a breakpoint (the list is closed).
        assert visited == ['source-tree', 'source-breakpoints-title', 'source-text', 'code-stack',
                           'code-watches', 'code-variables', 'code-projects', 'source-tree']
        table = app.query_one('#code-variables')
        table.focus()
        row = table.cursor_row
        await pilot.press('up')  # Arrows move between the variables.
        await pilot.pause()
        assert table.cursor_row == row - 1


async def test_alt_arrows_skip_the_hidden_debug_panes(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        app.query_one('#code-projects').focus()
        visited = []
        for _ in range(3):
            await pilot.press('alt+right')
            await pilot.pause()
            visited.append(app.focused.id)
        assert visited == ['source-tree', 'source-text', 'code-projects']


async def test_focus_returns_to_the_profiles_when_the_debug_panel_closes(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        table = await pause_on_answer(pilot, app)
        assert table.has_focus
        await pilot.press('f5')  # Continue: the program ends and the panel goes away.
        await until(pilot, lambda: 'RESULT:42' in output(app))
        await until(pilot, lambda: not app.query_one('#code-debug').display)
        await until(pilot, lambda: app.focused is not None
                    and app.focused.id == 'code-projects')
        await pilot.press('alt+right')  # The panes are reachable again.
        await pilot.pause()
        assert app.focused.id == 'source-tree'
