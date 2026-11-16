"""Debug console evaluation through the public session API, against real adapters."""

import asyncio
import sys

import pytest

from debugpilot.debugger import DebugError, GoDebugSession, NodeDebugSession, PythonDebugSession
from debugpilot.storage.code_projects import CodeProject


async def stopped(session, seconds=120):
    async with asyncio.timeout(seconds):
        while True:
            message = await session.events.get()
            if message.get('event') == 'stopped':
                return
            assert message.get('event') not in {'exited', 'terminated'}


PYTHON = 'orders = ["A-1", "A-2", "A-3"]\ntotal = 8\nprint(total)\n'


async def test_python_repl_context_runs_assignments(tmp_path):
    source = tmp_path / 'main.py'
    source.write_text(PYTHON)
    session = PythonDebugSession()
    try:
        await session.start(CodeProject('py', tmp_path, (sys.executable, '-u', 'main.py')),
                            {source: [3]})
        await stopped(session, 20)
        frame = (await session.stack())[0]['id']
        assert await session.evaluate('len(orders)', frame, context='repl') == '3'
        await session.evaluate('total = 99', frame, context='repl')
        assert await session.evaluate('total', frame) == '99'
        with pytest.raises(DebugError, match='ZeroDivisionError'):
            await session.evaluate('1 / 0', frame, context='repl')
    finally:
        await session.close()


async def test_python_watch_context_keeps_rejecting_statements(tmp_path):
    source = tmp_path / 'main.py'
    source.write_text(PYTHON)
    session = PythonDebugSession()
    try:
        await session.start(CodeProject('py', tmp_path, (sys.executable, '-u', 'main.py')),
                            {source: [3]})
        await stopped(session, 20)
        frame = (await session.stack())[0]['id']
        with pytest.raises(DebugError):
            await session.evaluate('total = 99', frame)
        assert await session.evaluate('total', frame) == '8'
    finally:
        await session.close()


async def test_go_repl_context_evaluates_expressions(tmp_path):
    (tmp_path / 'go.mod').write_text('module example.invalid/console\n\ngo 1.22\n')
    source = tmp_path / 'main.go'
    source.write_text(
        'package main\n\nimport "fmt"\n\nfunc main() {\n'
        '\torders := []string{"A-1", "A-2", "A-3"}\n'
        '\tfmt.Println(len(orders))\n}\n')
    session = GoDebugSession()
    try:
        await session.start(CodeProject('go', tmp_path, ('go', 'run', 'main.go')), {source: [7]})
        await stopped(session)
        frame = (await session.stack())[0]['id']
        assert await session.evaluate('len(orders)', frame, context='repl') == '3'
        assert await session.evaluate('orders[2]', frame, context='repl') == '"A-3"'
    finally:
        await session.close()


async def test_node_accepts_the_repl_context_and_runs_assignments(tmp_path):
    source = tmp_path / 'app.js'
    source.write_text('const orders = ["A-1", "A-2", "A-3"];\nlet total = 8;\n'
                      'console.log(total);\n')
    session = NodeDebugSession()
    try:
        await session.start(CodeProject('node', tmp_path, ('node', 'app.js')), {source: [3]})
        await stopped(session, 20)
        frame = (await session.stack())[0]['id']
        assert await session.evaluate('orders.length', frame, context='repl') == '3'
        await session.evaluate('total = 99', frame, context='repl')
        assert await session.evaluate('total', frame) == '99'
    finally:
        await session.close()


CRASH = (
    'def parse(text):\n'
    '    return int(text)\n'
    'orders = ["3", "5", "abc"]\n'
    'total = 0\n'
    'for quantity in orders:\n'
    '    total += parse(quantity)\n'
)


async def test_console_evaluates_in_the_selected_frame_with_history(monkeypatch, tmp_path):
    from test_code_project_store import configure
    from test_tui_grouping import Docker
    from textual.widgets import DataTable

    from debugpilot.core.engine import DebugPilotEngine
    from debugpilot.storage.config import Settings
    from debugpilot.tui.app import DebugPilotApp
    from debugpilot.tui.code_debug import CodeDebug

    store = configure(monkeypatch, tmp_path)
    root = tmp_path / 'one'
    root.mkdir()
    (root / 'main.py').write_text(CRASH, encoding='utf-8')
    store.path.write_text(__import__('json').dumps({'version': 1, 'configurations': [
        {'name': 'one', 'workspaceFolder': str(root),
         'command': [sys.executable, '-u', 'main.py']},
    ]}), encoding='utf-8')
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)

    async def until(pilot, condition, seconds=20):
        async with asyncio.timeout(seconds):
            while not condition():
                await pilot.pause(0.05)

    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        profiles = app.query_one('#code-projects', DataTable)
        profiles.focus()
        console = app.query_one('#code-debug-eval')
        assert not console.display
        await pilot.press('shift+f5')
        debug = app.query_one(CodeDebug)
        await until(pilot, lambda: debug.selected.execution is not None)
        assert console.display
        assert console.placeholder == 'Evaluate · Enter runs in main.py:2 · ↑↓ history'

        def output():
            return '\n'.join(debug.selected.output)

        profiles.focus()
        await pilot.press('colon')
        await until(pilot, lambda: app.focused is console)
        # The key only moves the focus; it is never typed into the field.
        await pilot.press(*'text')
        assert console.value == 'text'
        await pilot.press('enter')
        await until(pilot, lambda: "> text\n'abc'" in output())
        assert console.value == ''
        console.value = '1/0'
        await pilot.press('enter')
        await until(pilot, lambda: '> 1/0\n⚠ ZeroDivisionError: division by zero' in output())
        # The history recalls earlier lines, newest first; Down returns to an empty line.
        await pilot.press('up')
        assert console.value == '1/0'
        await pilot.press('up')
        assert console.value == 'text'
        await pilot.press('up')
        assert console.value == 'text'
        await pilot.press('down')
        assert console.value == '1/0'
        await pilot.press('down')
        assert console.value == ''

        # Another stack frame: the console follows it, and an assignment refreshes Variables.
        stack = app.query_one('#code-stack', DataTable)
        stack.focus()
        stack.move_cursor(row=1)
        await pilot.press('enter')
        await until(pilot, lambda: console.placeholder.endswith('main.py:6 · ↑↓ history'))
        await until(pilot, lambda: 'total = 8' in app.query_one('#code-variables').text)
        console.focus()
        console.value = 'total = 99'
        await pilot.press('enter')
        await until(pilot, lambda: 'total = 99' in app.query_one('#code-variables').text)
        # The assignment is echoed like any line; it has no value of its own.
        assert output().endswith('> total = 99')

        await pilot.press('escape')
        assert app.focused is profiles
        await pilot.press('f5')
        await until(pilot, lambda: 'Exited' in str(app.query_one('#code-run-state').render()))
        assert not console.display


async def test_one_field_switches_between_program_input_and_console(monkeypatch, tmp_path):
    from test_code_project_store import configure
    from test_tui_grouping import Docker

    from debugpilot.core.engine import DebugPilotEngine
    from debugpilot.storage.config import Settings
    from debugpilot.tui.app import DebugPilotApp
    from debugpilot.tui.code_debug import CodeDebug

    store = configure(monkeypatch, tmp_path)
    root = tmp_path / 'one'
    root.mkdir()
    (root / 'main.py').write_text('quantity = int(input("qty? "))\nprint(quantity)\n',
                                  encoding='utf-8')
    store.path.write_text(__import__('json').dumps({'version': 1, 'configurations': [
        {'name': 'one', 'workspaceFolder': str(root),
         'command': [sys.executable, '-u', 'main.py']},
    ]}), encoding='utf-8')
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)

    async def until(pilot, condition, seconds=20):
        async with asyncio.timeout(seconds):
            while not condition():
                await pilot.pause(0.05)

    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        program = app.query_one('#code-debug-input')
        console = app.query_one('#code-debug-eval')
        await pilot.press('shift+f5')
        debug = app.query_one(CodeDebug)
        await until(pilot, lambda: program.display and 'qty?' in '\n'.join(debug.selected.output))
        assert not console.display  # Running: only Program input.
        await pilot.press('p')
        await until(pilot, lambda: program.has_focus)
        await pilot.press(*'abc', 'enter')
        # The crash pauses the program: the same line becomes the console and keeps the keys.
        await until(pilot, lambda: console.display and not program.display)
        await until(pilot, lambda: console.has_focus)
        await pilot.press('s')  # Typed into the console, never Code's Stop.
        assert console.value == 's' and debug.selected.active
        await pilot.press('backspace')
        await pilot.press('f5')
        # Running again (it ends with the crash): Program input is back, the console hidden.
        await until(pilot, lambda: not console.display)
