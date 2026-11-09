"""Shift+F9 conditions and logpoints in the Code UI, through persistence and real debugpy."""

import asyncio

from test_code_debug_ui import Docker, debug_app, rendered
from test_tui_grouping import until
from textual.widgets import Input, Static, TextArea, Tree

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.debugger import PythonDebugSession
from debugpilot.storage.breakpoints import BreakpointOptions, BreakpointStore
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.breakpoint_dialog import BreakpointDialog
from debugpilot.tui.source_browser import SourceBrowser

# debug_app's main.py: 1 def increment, 2 return, 3 answer = 41, 4 increment, 5 print.


def store(tmp_path):
    return BreakpointStore(tmp_path / '.debugpilot' / 'projects' / 'breakpoints.json')


async def open_main(pilot, app, line):
    browser = app.query_one(SourceBrowser)
    tree = browser.query_one(Tree)
    if browser.file_path is None:
        tree.select_node(next(n for n in tree.root.children if str(n.label) == 'main.py'))
        await pilot.pause()
    editor = browser.query_one(TextArea)
    editor.move_cursor((line - 1, 0))
    editor.focus()
    await pilot.pause()
    return browser


async def edit(pilot, app, condition='', log=''):
    await pilot.press('shift+f9')
    await until(pilot, lambda: isinstance(app.screen, BreakpointDialog))
    app.screen.query_one('#breakpoint-condition', Input).value = condition
    app.screen.query_one('#breakpoint-log', Input).value = log
    await pilot.click('#breakpoint-save')
    await until(pilot, lambda: not isinstance(app.screen, BreakpointDialog))


def glyph(browser, line):
    return browser.query_one(TextArea).render_line(line - 1).text


def labels(browser):
    return [str(leaf.label) for leaf in browser.query_one(Tree).root.children[0].children]


async def test_condition_and_logpoint_marks_labels_and_persistence(monkeypatch, tmp_path):
    app, roots, _ = debug_app(monkeypatch, tmp_path)
    source = (roots[0] / 'main.py').resolve()
    key = (roots[0].resolve(), source)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        browser = await open_main(pilot, app, 4)
        await edit(pilot, app, condition='answer == 41')
        browser = await open_main(pilot, app, 5)
        await edit(pilot, app, log='result {answer}')
        await open_main(pilot, app, 3)
        await pilot.press('f9')  # F9 stays a plain breakpoint.
        assert browser.breakpoints(*key) == (3, 4, 5)
        assert '●' in glyph(browser, 3)
        assert '◆' in glyph(browser, 4)
        assert '◇' in glyph(browser, 5)
        assert labels(browser) == [
            'Line 3 · pending', 'Line 4 · if answer == 41 · pending',
            'Line 5 · log: result {answer} · pending']
        # The plain F9 save kept the other lines' options.
        assert store(tmp_path).load_options() == {key: {
            4: BreakpointOptions(condition='answer == 41'),
            5: BreakpointOptions(log_message='result {answer}')}}
        assert browser.options_snapshot(roots[0]) == {str(source): {
            4: BreakpointOptions(condition='answer == 41'),
            5: BreakpointOptions(log_message='result {answer}')}}
    restarted = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with restarted.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        browser = await open_main(pilot, restarted, 4)
        assert '◆' in glyph(browser, 4)
        assert '◇' in glyph(browser, 5)
        # F9 on a conditional line removes the breakpoint and its condition.
        await pilot.press('f9')
        assert browser.breakpoints(*key) == (3, 5)
        assert store(tmp_path).load_options() == {key: {
            5: BreakpointOptions(log_message='result {answer}')}}


async def test_dialog_prefills_removes_cancels_and_validates(monkeypatch, tmp_path):
    app, roots, _ = debug_app(monkeypatch, tmp_path)
    key = (roots[0].resolve(), (roots[0] / 'main.py').resolve())
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        browser = await open_main(pilot, app, 4)
        await edit(pilot, app, condition='answer > 1', log='seen {answer}')
        await pilot.press('shift+f9')
        await until(pilot, lambda: isinstance(app.screen, BreakpointDialog))
        assert app.screen.query_one('#breakpoint-condition', Input).value == 'answer > 1'
        assert app.screen.query_one('#breakpoint-log', Input).value == 'seen {answer}'
        await pilot.press('escape')
        await until(pilot, lambda: not isinstance(app.screen, BreakpointDialog))
        assert browser.breakpoints(*key) == (4,)
        await pilot.press('shift+f9')
        await until(pilot, lambda: isinstance(app.screen, BreakpointDialog))
        app.screen.query_one('#breakpoint-condition', Input).value = 'x' * 1001
        await pilot.click('#breakpoint-save')
        await pilot.pause()
        assert isinstance(app.screen, BreakpointDialog)
        assert '1000 characters' in str(app.screen.query_one('#breakpoint-status', Static).render())
        await pilot.click('#breakpoint-remove')
        await until(pilot, lambda: not isinstance(app.screen, BreakpointDialog))
        assert browser.breakpoints(*key) == ()
        assert store(tmp_path).load_options() == {}
        # Saving with both fields blank makes a plain breakpoint.
        await edit(pilot, app)
        assert browser.breakpoints(*key) == (4,)
        assert '●' in glyph(browser, 4)


async def test_real_logpoint_writes_debug_output_without_stopping(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        await open_main(pilot, app, 4)
        await edit(pilot, app, log='before {answer}')
        await pilot.press('shift+f5')
        async with asyncio.timeout(30):
            while 'Exited: 0' not in rendered(app, '#code-run-state'):
                assert 'Debug stopped' not in rendered(app, '#code-run-state')
                await pilot.pause(0.05)
        output = '\n'.join(line.text for line in app.query_one('#code-debug-output').lines)
        assert 'before 41' in output
        assert 'RESULT:42' in output


async def test_editing_a_condition_while_debugging_updates_the_session(monkeypatch, tmp_path):
    calls = []
    original = PythonDebugSession.set_breakpoints

    async def recording(self, source, lines, options=None):
        calls.append((lines, options))
        return await original(self, source, lines, options)

    monkeypatch.setattr(PythonDebugSession, 'set_breakpoints', recording)
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        await open_main(pilot, app, 5)
        await pilot.press('f9')
        await pilot.press('shift+f5')
        async with asyncio.timeout(30):
            while 'Debug stopped' not in rendered(app, '#code-run-state'):
                await pilot.pause(0.05)
        # The plain breakpoint carries no options at startup.
        assert calls[-1][0] == (5,) and not calls[-1][1]
        await open_main(pilot, app, 5)
        await edit(pilot, app, condition='answer == 0')
        await until(pilot, lambda: calls[-1] == ((5,), {5: BreakpointOptions(
            condition='answer == 0')}))
        await pilot.click('#code-continue')
        await until(pilot, lambda: 'Exited: 0' in rendered(app, '#code-run-state'))


async def test_label_shows_condition_and_log_message_together(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        browser = await open_main(pilot, app, 4)
        await edit(pilot, app, condition='answer > 1', log='seen {answer}')
        assert labels(browser) == ['Line 4 · if answer > 1 · log: seen {answer} · pending']
        assert '◇' in glyph(browser, 4)
