"""Code TUI: pausing on exceptions with a real debugpy adapter."""

import asyncio
import json
import sys

from test_code_project_store import configure
from test_tui_grouping import Docker
from textual.widgets import DataTable, TextArea

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.storage.exception_modes import ExceptionModeStore
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.code_debug import CodeDebug
from debugpilot.tui.source_browser import SourceBrowser

CRASH = 'def parse(text):\n    return int(text)\nparse("abc")\n'


def crash_app(monkeypatch, tmp_path):
    store = configure(monkeypatch, tmp_path)
    root = tmp_path / 'one'
    root.mkdir()
    (root / 'main.py').write_text(CRASH, encoding='utf-8')
    store.path.write_text(json.dumps({'version': 1, 'configurations': [
        {'name': 'one', 'workspaceFolder': str(root),
         'command': [sys.executable, '-u', 'main.py']},
    ]}), encoding='utf-8')
    return DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path), root


def output_border(app):
    """The Debug output's top border as drawn, with its title (it has no bottom border)."""
    output = app.query_one('#code-debug-output')
    return ''.join(segment.text for segment in output.render_lines(output.region.reset_offset)[0])


def run_state(app):
    return str(app.query_one('#code-run-state').render())


async def wait_for(pilot, condition, seconds=20):
    async with asyncio.timeout(seconds):
        while not condition():
            await pilot.pause(0.05)


async def test_uncaught_exception_pauses_with_its_message_and_location(monkeypatch, tmp_path):
    app, root = crash_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        app.query_one('#code-projects', DataTable).focus()
        await pilot.press('shift+f5')
        await wait_for(pilot, lambda: 'Paused on exception' in run_state(app))
        assert run_state(app).startswith(
            "Paused on exception: ValueError: invalid literal for int() with base 10: 'abc'")
        debug = app.query_one(CodeDebug)
        output = '\n'.join(debug.selected.output)
        assert "[exception] ValueError: invalid literal for int() with base 10: 'abc'" in output
        assert 'Exceptions: uncaught' in output_border(app)
        source = app.query_one(SourceBrowser).query_one(TextArea)
        await wait_for(pilot, lambda: '▶' in source.render_line(1).text)
        # The key applies to the paused session right away.
        app.query_one('#code-projects', DataTable).focus()
        await pilot.press('e')
        await wait_for(pilot, lambda: debug.session.exception_mode == 'all')
        await wait_for(pilot, lambda: 'Exceptions: all' in output_border(app))


async def test_key_cycles_and_remembers_the_mode_for_the_next_launch(monkeypatch, tmp_path):
    app, root = crash_app(monkeypatch, tmp_path)
    store = ExceptionModeStore()
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        app.query_one('#code-projects', DataTable).focus()
        await pilot.press('e')
        assert store.load() == {root.resolve(): 'all'}
        await pilot.press('e')
        assert store.load() == {root.resolve(): 'none'}
        await pilot.press('shift+f5')
        # Pausing is off, so the crash ends the program as before.
        await wait_for(pilot, lambda: 'Exited: 1' in run_state(app))
        app.query_one('#code-projects', DataTable).focus()
        await pilot.press('e')
        assert store.load() == {}
    assert ExceptionModeStore().load() == {}


GO_PANIC = (
    'package main\n\n'
    'func parse(text string) int {\n'
    '\tpanic("invalid quantity " + text)\n'
    '}\n\n'
    'func main() {\n'
    '\tparse("abc")\n'
    '}\n'
)


async def test_exception_in_runtime_code_selects_the_projects_own_frame(monkeypatch, tmp_path):
    store = configure(monkeypatch, tmp_path)
    root = tmp_path / 'go'
    root.mkdir()
    (root / 'go.mod').write_text('module example.invalid/panic\n\ngo 1.22\n', encoding='utf-8')
    (root / 'main.go').write_text(GO_PANIC, encoding='utf-8')
    store.path.write_text(json.dumps({'version': 1, 'configurations': [
        {'name': 'go', 'workspaceFolder': str(root), 'command': ['go', 'run', 'main.go']},
    ]}), encoding='utf-8')
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        app.query_one('#code-projects', DataTable).focus()
        await pilot.press('shift+f5')
        await wait_for(pilot, lambda: 'Paused on exception' in run_state(app), 120)
        debug = app.query_one(CodeDebug)
        # Delve stops inside runtime/panic.go; the panicking function of the project is chosen.
        await wait_for(pilot, lambda: debug.selected.execution is not None)
        frames = debug.selected.frames
        assert 'panic.go' in frames[0]['source']['path']
        row = debug.selected.frame_row
        assert frames[row]['name'] == 'main.parse' and frames[row]['line'] == 4
        assert app.query_one('#code-stack', DataTable).cursor_row == row
        assert debug.selected.execution[1:] == (root / 'main.go', 4)
        source = app.query_one(SourceBrowser).query_one(TextArea)
        await wait_for(pilot, lambda: '▶' in source.render_line(3).text)
        assert 'text' in app.query_one('#code-variables').text


def test_own_frame_skips_frames_without_or_outside_project_sources(tmp_path):
    from debugpilot.tui.code_debug import _own_frame

    inside = str(tmp_path / 'app.js')
    frames = [{'name': 'readFileSync', 'source': {}},
              {'name': 'internal', 'source': {'path': '/usr/lib/node/fs.js'}},
              {'name': 'loadSettings', 'source': {'path': inside}}]
    assert _own_frame(frames, tmp_path) == 2
    # Nothing of the project on the stack: the top frame, as for any other pause.
    assert _own_frame(frames[:2], tmp_path) == 0
    assert _own_frame([], tmp_path) == 0
