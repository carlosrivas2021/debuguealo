"""Ctrl+F10 runs a paused program to the source cursor's line, through real adapters."""

import asyncio
import json
import sys

import pytest
from test_code_project_store import configure
from test_tui_grouping import Docker
from textual.widgets import TextArea

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.code_debug import CodeDebug
from debugpilot.tui.source_browser import SourceBrowser

# Line 1 starts; line 3 runs once per pass of the loop; line 5 ends.
PROGRAMS = {
    'python': ('main.py', [sys.executable, '-u', 'main.py'],
               'total = 0\nfor n in range(3):\n    total += n\n\nprint(total)\n'),
    'node': ('main.js', ['node', 'main.js'],
             'let total = 0;\nfor (let n = 0; n < 3; n++) {\n  total += n;\n}\n'
             'console.log(total);\n'),
    'go': ('main.go', ['go', 'run', 'main.go'],
           'package main\n\nimport "fmt"\n\nfunc main() {\n\ttotal := 0\n'
           '\tfor n := 0; n < 3; n++ {\n\t\ttotal += n\n\t}\n\tfmt.Println(total)\n}\n'),
}
# (start breakpoint, loop body, a later line) for each program.
LINES = {'python': (1, 3, 5), 'node': (1, 3, 5), 'go': (6, 8, 10)}


async def until(pilot, condition, seconds=20):
    async with asyncio.timeout(seconds):
        while not condition():
            await pilot.pause(0.05)


def app_for(monkeypatch, tmp_path, language):
    store = configure(monkeypatch, tmp_path)
    root = tmp_path / 'one'
    root.mkdir()
    name, command, text = PROGRAMS[language]
    (root / name).write_text(text, encoding='utf-8')
    if language == 'go':
        (root / 'go.mod').write_text('module example.invalid/cursor\n\ngo 1.22\n')
    store.path.write_text(json.dumps({'version': 1, 'configurations': [
        {'name': 'one', 'workspaceFolder': str(root), 'command': command}]}), encoding='utf-8')
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    return app, (root / name).resolve()


async def cursor_to(pilot, app, source, line):
    browser = app.query_one(SourceBrowser)
    if browser.file_path != source:
        browser.open_source(browser.root_path, source)
    editor = browser.query_one(TextArea)
    editor.move_cursor((line - 1, 0))
    editor.focus()
    await pilot.pause()
    return browser


def paused_at(app):
    context = app.query_one(CodeDebug).selected
    if context is None or context.execution is None or context.session.state != 'stopped':
        return None
    return context.execution[2]


@pytest.mark.parametrize('language', ['python', 'node', 'go'])
async def test_run_to_cursor_stops_once_and_leaves_no_breakpoint(
        monkeypatch, tmp_path, language):
    app, source = app_for(monkeypatch, tmp_path, language)
    start, body, _later = LINES[language]
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        browser = await cursor_to(pilot, app, source, start)
        await pilot.press('f9')
        await pilot.press('shift+f5')
        async with asyncio.timeout(120):
            while paused_at(app) != start:
                await pilot.pause(0.05)
        await cursor_to(pilot, app, source, body)
        await pilot.press('ctrl+f10')
        await until(pilot, lambda: paused_at(app) == body, 60)
        session = app.query_one(CodeDebug).session
        # The one-shot line is gone as soon as it paused; the marks never changed.
        await until(pilot, lambda: tuple(
            session.requested_breakpoints.get(str(source), ())) == (start,))
        assert browser.breakpoints(source.parent, source) == (start,)
        assert '▶' in browser.query_one(TextArea).render_line(body - 1).text
        # Continue runs the rest of the loop without stopping on that line again.
        await pilot.press('f5')
        await until(pilot, lambda: 'Exited' in str(app.query_one('#code-run-state').render())
                    or 'finalizado' in str(app.query_one('#code-run-state').render()), 60)


async def test_a_breakpoint_on_the_way_stops_first_and_the_one_shot_line_is_dropped(
        monkeypatch, tmp_path):
    app, source = app_for(monkeypatch, tmp_path, 'python')
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        browser = await cursor_to(pilot, app, source, 1)
        await pilot.press('f9')
        await cursor_to(pilot, app, source, 3)
        await pilot.press('f9')
        await pilot.press('shift+f5')
        await until(pilot, lambda: paused_at(app) == 1, 30)
        await cursor_to(pilot, app, source, 5)
        await pilot.press('ctrl+f10')
        # The breakpoint on line 3 comes first, like with Continue.
        await until(pilot, lambda: paused_at(app) == 3, 30)
        session = app.query_one(CodeDebug).session
        await until(pilot, lambda: tuple(
            session.requested_breakpoints.get(str(source), ())) == (1, 3))
        assert browser.breakpoints(source.parent, source) == (1, 3)


async def test_run_to_cursor_needs_a_paused_program(monkeypatch, tmp_path):
    app, source = app_for(monkeypatch, tmp_path, 'python')
    notes = []
    async with app.run_test(size=(140, 52)) as pilot:
        monkeypatch.setattr(app, 'notify', lambda message, **_: notes.append(message))
        await pilot.click('#area-code')
        await cursor_to(pilot, app, source, 3)
        await pilot.press('ctrl+f10')
        await pilot.pause()
        assert notes == ['Run to cursor works while the program is paused.']


def python_app(monkeypatch, tmp_path, text):
    app, source = app_for(monkeypatch, tmp_path, 'python')
    source.write_text(text, encoding='utf-8')
    return app, source


async def start_paused_at(pilot, app, source, line, marks):
    await pilot.click('#area-code')
    browser = None
    for mark in marks:
        browser = await cursor_to(pilot, app, source, mark)
        await pilot.press('f9')
    await pilot.press('shift+f5')
    await until(pilot, lambda: paused_at(app) == line, 30)
    return browser


async def test_a_file_with_hit_counts_is_refused_so_counts_never_restart(monkeypatch, tmp_path):
    from debugpilot.storage.breakpoints import BreakpointOptions

    app, source = python_app(monkeypatch, tmp_path,
                             'total = 0\nfor n in range(6):\n    total += n\n\nprint(total)\n')
    notes = []
    async with app.run_test(size=(140, 52)) as pilot:
        browser = await start_paused_at(pilot, app, source, 1, [1])
        # A hit count on line 3: sending the file again would make it count from zero.
        browser._apply_breakpoint((source.parent, source), 3, True,
                                  BreakpointOptions(hit_condition='2'))
        monkeypatch.setattr(app, 'notify', lambda message, **_: notes.append(message))
        await cursor_to(pilot, app, source, 5)
        await pilot.press('ctrl+f10')
        await pilot.pause(0.3)
        assert notes == ['Run to cursor is not available in a file with hit-count breakpoints: '
                         'it would restart their counts.']
        assert paused_at(app) == 1  # Still paused; nothing was sent or continued.


async def test_a_conditional_or_logpoint_cursor_line_still_stops(monkeypatch, tmp_path):
    from debugpilot.storage.breakpoints import BreakpointOptions

    app, source = python_app(monkeypatch, tmp_path,
                             'total = 0\nfor n in range(3):\n    total += n\n\nprint(total)\n')
    async with app.run_test(size=(140, 52)) as pilot:
        browser = await start_paused_at(pilot, app, source, 1, [1])
        logpoint = BreakpointOptions(log_message='total={total}')
        browser._apply_breakpoint((source.parent, source), 5, True, logpoint)
        session = app.query_one(CodeDebug).session
        await cursor_to(pilot, app, source, 5)
        await pilot.press('ctrl+f10')
        # Plain while running to it, so the logpoint never lets the program go past.
        await until(pilot, lambda: paused_at(app) == 5, 30)
        # Then the line is a logpoint again.
        await until(pilot, lambda: session.breakpoint_options.get(str(source), {}).get(5)
                    == logpoint)
        assert session.requested_breakpoints[str(source)] == (1, 5)


async def test_editing_marks_while_running_keeps_the_target_line(monkeypatch, tmp_path):
    app, source = python_app(monkeypatch, tmp_path,
                             'import time\ntime.sleep(1.5)\nx = 1\ny = 2\nprint(x + y)\n')
    async with app.run_test(size=(140, 52)) as pilot:
        browser = await start_paused_at(pilot, app, source, 1, [1])
        await cursor_to(pilot, app, source, 4)
        await pilot.press('ctrl+f10')
        await until(pilot, lambda: paused_at(app) is None)
        # F9 on line 5 while it sleeps: the target line 4 must survive the update.
        await cursor_to(pilot, app, source, 5)
        await pilot.press('f9')
        await until(pilot, lambda: paused_at(app) is not None, 30)
        assert paused_at(app) == 4
        session = app.query_one(CodeDebug).session
        await until(pilot, lambda: tuple(session.requested_breakpoints[str(source)]) == (1, 5))
        assert browser.breakpoints(source.parent, source) == (1, 5)


async def test_stopping_forgets_the_one_shot_target(monkeypatch, tmp_path):
    app, source = python_app(monkeypatch, tmp_path,
                             'import time\ntime.sleep(3)\nx = 1\nprint(x)\n')
    async with app.run_test(size=(140, 52)) as pilot:
        await start_paused_at(pilot, app, source, 1, [1])
        await cursor_to(pilot, app, source, 3)
        await pilot.press('ctrl+f10')
        debug = app.query_one(CodeDebug)
        await until(pilot, lambda: debug.selected.run_to is not None)
        await pilot.click('#code-stop')
        await until(pilot, lambda: not debug.selected.active, 30)
        assert debug.selected.run_to is None
