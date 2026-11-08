"""F9 toggles the requested breakpoint at the source cursor, as the button does."""

import pytest
from test_code_debug_ui import FakeDebug, debug_app, until
from textual.widgets import TextArea, Tree

from debugpilot.tui import code_debug
from debugpilot.tui.source_browser import SourceBrowser


@pytest.fixture
def app_state(monkeypatch, tmp_path):
    return debug_app(monkeypatch, tmp_path)


async def open_source(pilot, app, line=4):
    browser = app.query_one(SourceBrowser)
    tree = browser.query_one(Tree)
    tree.select_node(next(n for n in tree.root.children if str(n.label) == 'main.py'))
    await pilot.pause()
    editor = browser.query_one(TextArea)
    editor.move_cursor((line - 1, 0))
    editor.focus()
    await pilot.pause()
    return browser


async def test_f9_adds_and_removes_breakpoint_from_focused_source(app_state):
    app, roots, _ = app_state
    source = roots[0] / 'main.py'
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        browser = await open_source(pilot, app)

        await pilot.press('f9')
        assert browser.breakpoints(roots[0], source) == (4,)
        assert browser.breakpoint_store.load()[(roots[0].resolve(), source.resolve())] == (4,)

        await pilot.press('f9')
        assert browser.breakpoints(roots[0], source) == ()


async def test_f9_reaches_the_active_debug_session(app_state, monkeypatch):
    app, roots, _ = app_state
    FakeDebug.instances = []
    FakeDebug.gate = FakeDebug.failure = None
    monkeypatch.setattr(code_debug, 'PythonDebugSession', FakeDebug)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await until(pilot, lambda: bool(FakeDebug.instances))
        session = FakeDebug.instances[0]
        await until(pilot, lambda: session.state == 'stopped')
        await open_source(pilot, app, line=2)

        await pilot.press('f9')
        await until(pilot, lambda: bool(session.updates))

        assert session.updates[-1] == (str((roots[0] / 'main.py').resolve()), (2,))


async def test_f9_without_open_source_warns_and_marks_nothing(app_state):
    app, _, _ = app_state
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')

        await pilot.press('f9')
        await pilot.pause()

        messages = [item.message for item in app._notifications]
        assert 'Open a source file before toggling a breakpoint.' in messages
        assert not app.query_one(SourceBrowser).breakpoint_store.load()


@pytest.mark.parametrize('key', ['f5', 'f9'])
async def test_debug_keys_outside_code_point_to_the_code_area(app_state, key):
    app, roots, _ = app_state
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-containers')

        await pilot.press(key)
        await pilot.pause()

        messages = [item.message for item in app._notifications]
        assert 'Debugger controls are available in the Code area.' in messages
        assert not app.query_one(SourceBrowser).breakpoints(roots[0], roots[0] / 'main.py')
