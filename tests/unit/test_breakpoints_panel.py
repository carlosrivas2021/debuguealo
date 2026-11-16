"""Switched-off breakpoints and the sidebar Breakpoints list, through real debugpy."""

from test_breakpoint_options_ui import edit, glyph, labels, open_main, store
from test_code_debug_ui import debug_app, rendered
from test_tui_grouping import until

from debugpilot.storage.breakpoints import BreakpointOptions

# debug_app's main.py: 1 def increment, 2 return, 3 answer = 41, 4 increment, 5 print.


async def test_a_disabled_breakpoint_is_kept_but_never_stops(monkeypatch, tmp_path):
    app, roots, _ = debug_app(monkeypatch, tmp_path)
    source = (roots[0] / 'main.py').resolve()
    key = (roots[0].resolve(), source)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        browser = await open_main(pilot, app, 3)
        await pilot.press('f9')
        await open_main(pilot, app, 4)
        await edit(pilot, app, condition='answer == 41')
        browser.set_enabled({key: {4}}, False)
        await pilot.pause()
        # Off, it keeps its line and condition: grey ring in the gutter, "off" in the tree.
        assert browser.breakpoints(*key) == (3, 4)
        assert '○' in glyph(browser, 4) and '●' in glyph(browser, 3)
        assert labels(browser) == [' ● main.py:3', ' ○ main.py:4 if answer == 41 (off)']
        assert store(tmp_path).load_disabled() == {key: (4,)}
        assert store(tmp_path).load_options() == {key: {
            4: BreakpointOptions(condition='answer == 41')}}
        assert browser.breakpoint_snapshot(roots[0]) == {str(source): (3,)}
        assert browser.options_snapshot(roots[0]) == {}

        await pilot.press('shift+f5')
        debug = app.query_one('#code-debug')
        await until(pilot, lambda: debug.selected is not None
                    and debug.selected.execution is not None)
        assert debug.selected.execution[2] == 3
        # Switched back on while paused, the live session stops there next.
        browser.set_enabled({key: {4}}, True)
        await until(pilot, lambda: debug.session.requested_breakpoints.get(str(source))
                    == (3, 4))
        await pilot.click('#code-continue')
        await until(pilot, lambda: debug.selected.execution is not None
                    and debug.selected.execution[2] == 4)
        assert labels(browser)[1] == '▶◆ main.py:4 if answer == 41'
        # Off again: Continue runs to the end instead of stopping.
        browser.set_enabled({key: {3, 4}}, False)
        await until(pilot, lambda: debug.session.requested_breakpoints.get(str(source)) == ())
        await pilot.click('#code-continue')
        await until(pilot, lambda: 'Exited: 0' in rendered(app, '#code-run-state'))
        # F9 on a disabled line removes it, with its condition.
        await open_main(pilot, app, 4)
        await pilot.press('f9')
        assert browser.breakpoints(*key) == (3,)
        assert store(tmp_path).load_disabled() == {key: (3,)}
        assert store(tmp_path).load_options() == {}


def listed(app):
    table = app.query_one('#source-breakpoints')
    return [' '.join(str(cell) for cell in table.get_row_at(row)).rstrip()
            for row in range(table.row_count)] if table.display else []


def title(app):
    return app.query_one('#source-breakpoints-title').text


async def test_the_sidebar_lists_opens_switches_and_removes_breakpoints(monkeypatch, tmp_path):
    from textual.widgets import DataTable, TextArea

    from debugpilot.tui.source_browser import SourceBrowser

    app, roots, _ = debug_app(monkeypatch, tmp_path)
    (roots[0] / 'lib').mkdir()
    (roots[0] / 'lib' / 'util.py').write_text('VALUE = 1\nOTHER = 2\n', encoding='utf-8')
    root, main = roots[0].resolve(), (roots[0] / 'main.py').resolve()
    util = (roots[0] / 'lib' / 'util.py').resolve()
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        assert listed(app) == [] and title(app) == 'BREAKPOINTS F9 adds one'
        browser = await open_main(pilot, app, 4)
        await edit(pilot, app, condition='answer == 41')
        await open_main(pilot, app, 3)
        await pilot.press('f9')
        browser.open_source(roots[0], util, 2)
        await pilot.pause()
        await pilot.press('f9')
        # Closed at first: only the title, with the count.
        assert title(app) == 'BREAKPOINTS 3 ▸' and listed(app) == []
        await pilot.click('#source-breakpoints-title')
        assert title(app) == 'BREAKPOINTS 3 ▾'
        # By file, then line, with each one's kind and condition.
        assert listed(app) == [' ● lib/util.py:2', ' ● main.py:3', ' ◆ main.py:4 if answer == 41']

        # Only the selected profile's project is listed.
        profiles = app.query_one('#code-projects', DataTable)
        profiles.move_cursor(row=1)
        await until(pilot, lambda: title(app) == 'BREAKPOINTS F9 adds one')
        assert listed(app) == []
        profiles.move_cursor(row=0)
        # Still open for the rest of the session.
        await until(pilot, lambda: title(app) == 'BREAKPOINTS 3 ▾')

        # Ctrl+Right from the file tree reaches the title, then the list.
        browser.query_one('#source-tree').focus()
        await pilot.press('ctrl+right')
        assert app.focused is app.query_one('#source-breakpoints-title')
        await pilot.press('ctrl+right')
        table = app.query_one('#source-breakpoints')
        assert app.focused is table
        table.move_cursor(row=2)
        await pilot.press('space')
        assert listed(app)[2] == ' ○ main.py:4 if answer == 41 (off)'
        assert store(tmp_path).load_disabled() == {(root, main): (4,)}
        assert browser.breakpoint_snapshot(roots[0]) == {str(util): (2,), str(main): (3,)}
        await pilot.press('space')
        assert listed(app)[2] == ' ◆ main.py:4 if answer == 41'
        assert store(tmp_path).load_disabled() == {}

        # A: all off while any is on, then all back on.
        await pilot.press('space', 'a')
        assert all('(off)' in row for row in listed(app))
        assert browser.breakpoint_snapshot(roots[0]) == {}
        await pilot.press('a')
        assert not any('(off)' in row for row in listed(app))
        assert store(tmp_path).load_disabled() == {}

        # Delete removes the line, with its options; the cursor stays on the list.
        table.move_cursor(row=0)
        await pilot.press('delete')
        assert listed(app) == [' ● main.py:3', ' ◆ main.py:4 if answer == 41']
        assert store(tmp_path).load() == {(root, main): (3, 4)}
        assert browser.breakpoints(root, util) == ()

        # Enter opens the line in the editor.
        table.move_cursor(row=1)
        await pilot.press('enter')
        editor = browser.query_one(TextArea)
        assert browser.file_path == main and app.focused is editor
        assert editor.cursor_location == (3, 0)

        # While debugging, the row of the paused line is marked.
        await pilot.press('shift+f5')
        await until(pilot, lambda: listed(app)[0] == '▶● main.py:3')
        assert listed(app)[1] == ' ◆ main.py:4 if answer == 41'
        await pilot.click('#code-continue')
        await until(pilot, lambda: listed(app)[1] == '▶◆ main.py:4 if answer == 41')
        assert listed(app)[0] == ' ● main.py:3'
        await pilot.click('#code-continue')
        await until(pilot, lambda: 'Exited: 0' in rendered(app, '#code-run-state'))
        assert listed(app) == [' ● main.py:3', ' ◆ main.py:4 if answer == 41']
        assert isinstance(app.query_one(SourceBrowser), SourceBrowser)


async def test_the_list_starts_closed_and_its_title_opens_and_closes_it(monkeypatch, tmp_path):
    from test_code_debug_ui import Docker

    from debugpilot.core.engine import DebugPilotEngine
    from debugpilot.storage.config import Settings
    from debugpilot.tui.app import DebugPilotApp

    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        await open_main(pilot, app, 3)
        await pilot.press('f9')
        heading = app.query_one('#source-breakpoints-title')
        idle = heading.styles.background
        heading.focus()
        await pilot.pause()
        # Focused, the title looks selected, so Alt/Ctrl+arrows never land out of sight.
        assert heading.styles.background != idle
        await pilot.press('enter')
        assert title(app) == 'BREAKPOINTS 1 ▾' and listed(app) == [' ● main.py:3']
        # Enter opens it and moves into it, ready to pick a breakpoint.
        table = app.query_one('#source-breakpoints')
        assert app.focused is table
        heading.focus()
        await pilot.press('space')
        assert title(app) == 'BREAKPOINTS 1 ▸' and listed(app) == []
        assert app.focused is heading
        # With the list closed, Ctrl+Right skips from the title to the source.
        await pilot.press('ctrl+right')
        assert app.focused is app.query_one('#source-text')
        await pilot.press('space')  # In the source, Space is not the title's.
        assert title(app) == 'BREAKPOINTS 1 ▸'
        heading.focus()
        await pilot.press('enter')
        assert listed(app) == [' ● main.py:3']
    # Every session starts with it closed, whatever it was before.
    restarted = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with restarted.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        assert title(restarted) == 'BREAKPOINTS 1 ▸' and listed(restarted) == []
