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
        assert labels(browser) == ['Line 3 · pending', 'Line 4 · if answer == 41 · off']
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
        assert labels(browser)[1].startswith('Line 4 · if answer == 41 · ')
        assert 'off' not in labels(browser)[1]
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
