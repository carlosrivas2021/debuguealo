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
        assert debug.output.border_subtitle == 'Exceptions: uncaught'
        source = app.query_one(SourceBrowser).query_one(TextArea)
        await wait_for(pilot, lambda: '▶' in source.render_line(1).text)
        # The key applies to the paused session right away.
        app.query_one('#code-projects', DataTable).focus()
        await pilot.press('e')
        await wait_for(pilot, lambda: debug.session.exception_mode == 'all')
        assert debug.output.border_subtitle == 'Exceptions: all'


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
