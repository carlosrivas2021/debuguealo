"""WATCH section of the Code debug panel, with real debugpy."""

import asyncio

from test_code_debug_ui import Docker, debug_app, mark, rendered
from test_tui_grouping import until
from textual.widgets import DataTable, Input

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.storage.watches import WatchStore
from debugpilot.tui.app import DebugPilotApp

# debug_app's main.py: 1 def increment(value), 2 return value + 1, 3 answer = 41,
# 4 answer = increment(answer), 5 print(...).


def watch_rows(app):
    table = app.query_one('#code-watches', DataTable)
    return [tuple(str(cell) for cell in table.get_row_at(row)) for row in range(table.row_count)]


async def wait_rows(pilot, app, expected):
    async with asyncio.timeout(15):
        while watch_rows(app) != expected:
            await pilot.pause(0.05)


async def wait_state(pilot, app, text):
    async with asyncio.timeout(30):
        while text not in rendered(app, '#code-run-state'):
            assert 'Unable to debug' not in rendered(app, '#code-run-state')
            await pilot.pause(0.05)


async def add_watch(pilot, app, expression):
    field = app.query_one('#code-watch-input', Input)
    field.focus()
    field.value = expression
    await pilot.press('enter')


async def test_watches_evaluate_per_pause_show_errors_and_persist(monkeypatch, tmp_path):
    app, roots, _ = debug_app(monkeypatch, tmp_path)
    store = WatchStore(tmp_path / '.debugpilot' / 'projects' / 'watches.json')
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        await mark(pilot, app, 4)
        await pilot.press('shift+f5')
        await wait_state(pilot, app, 'Debug stopped')
        await add_watch(pilot, app, 'answer + 1')
        await add_watch(pilot, app, 'missing_name')
        await add_watch(pilot, app, '  answer  ')
        await until(pilot, lambda: len(watch_rows(app)) == 3)
        async with asyncio.timeout(15):
            while watch_rows(app)[0][1] != '42' or watch_rows(app)[2][1] != '41':
                await pilot.pause(0.05)
        expression, error = watch_rows(app)[1]
        assert expression == 'missing_name'
        assert error.startswith('⚠ ') and 'missing_name' in error
        assert store.load() == {roots[0].resolve(): ('answer + 1', 'missing_name', 'answer')}
        # A step is a new pause: every watch is evaluated again.
        await pilot.press('f10')
        async with asyncio.timeout(15):
            while watch_rows(app)[0][1] != '43':
                await pilot.pause(0.05)
        # Delete removes the selected watch.
        table = app.query_one('#code-watches', DataTable)
        table.focus()
        table.move_cursor(row=1)
        await pilot.press('delete')
        await until(pilot, lambda: [row[0] for row in watch_rows(app)] == ['answer + 1', 'answer'])
        assert store.load() == {roots[0].resolve(): ('answer + 1', 'answer')}
        await pilot.click('#code-continue')
        await wait_state(pilot, app, 'Exited: 0')
        assert watch_rows(app) == [('answer + 1', '—'), ('answer', '—')]
    restarted = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with restarted.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        # Line 4's breakpoint is restored too; the restored watches are evaluated there.
        await pilot.press('shift+f5')
        await wait_rows(pilot, restarted, [('answer + 1', '42'), ('answer', '41')])
        await pilot.click('#code-continue')
        await wait_state(pilot, restarted, 'Exited: 0')


async def test_watches_follow_the_selected_stack_frame(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        await mark(pilot, app, 2)  # Inside increment(value).
        await pilot.press('shift+f5')
        await wait_state(pilot, app, 'Debug stopped')
        await add_watch(pilot, app, 'value')
        await wait_rows(pilot, app, [('value', '41')])
        stack = app.query_one('#code-stack', DataTable)
        stack.focus()
        stack.move_cursor(row=1)  # The module frame has no `value`.
        await pilot.press('enter')
        async with asyncio.timeout(15):
            while not watch_rows(app)[0][1].startswith('⚠ '):
                await pilot.pause(0.05)
        await pilot.click('#code-continue')
        await wait_state(pilot, app, 'Exited: 0')


async def test_blank_and_duplicate_watches_are_not_added(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        await mark(pilot, app, 4)
        await pilot.press('shift+f5')
        await wait_state(pilot, app, 'Debug stopped')
        await add_watch(pilot, app, 'answer')
        await add_watch(pilot, app, '   ')
        await add_watch(pilot, app, 'answer')
        await wait_rows(pilot, app, [('answer', '41')])
        assert app.query_one('#code-watch-input', Input).value == ''
        await pilot.click('#code-continue')
        await wait_state(pilot, app, 'Exited: 0')
