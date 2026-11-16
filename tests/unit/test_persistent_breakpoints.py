from test_code_debug_ui import Docker, debug_app, labels, mark, rendered
from textual.widgets import TextArea

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.breakpoints import BreakpointStore
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.source_browser import SourceBrowser


async def test_code_workspace_restores_and_persists_marks_across_recreation(
    monkeypatch, tmp_path
):
    app, roots, launch_store = debug_app(monkeypatch, tmp_path)
    launch_before = launch_store.path.read_bytes()
    source = roots[0] / 'main.py'
    source_before = source.read_bytes()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        browser = await mark(pilot, app, 4)
        assert browser.breakpoints(roots[0], roots[0] / 'main.py') == (4,)
        browser.set_verification(roots[0], {str(source): [{'verified': True, 'line': 4}]})
        assert labels(browser) == [' ● main.py:4']
        browser.set_verification(roots[0], {str(source): [{'verified': False, 'line': 4}]})
        assert labels(browser) == [' ● main.py:4 unverified']
    assert source.read_bytes() == source_before
    assert launch_store.path.read_bytes() == launch_before
    restarted = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with restarted.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        browser = restarted.query_one(SourceBrowser)
        assert browser.open_source(roots[0], roots[0] / 'main.py', 4)
        assert browser.breakpoints(roots[0], roots[0] / 'main.py') == (4,)
        assert 4 in browser.query_one(TextArea).breakpoint_lines
        # Verification is never saved: the restored mark has no note.
        assert labels(browser) == [' ● main.py:4']
        assert browser.breakpoint_snapshot(roots[1]) == {}
        assert launch_store.path.read_bytes() == launch_before
        await pilot.click('#source-breakpoint')
        assert browser.breakpoints(roots[0], roots[0] / 'main.py') == ()
    restarted_again = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path
    )
    async with restarted_again.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        browser = restarted_again.query_one(SourceBrowser)
        assert browser.open_source(roots[0], roots[0] / 'main.py', 1)
        assert browser.breakpoints(roots[0], roots[0] / 'main.py') == ()
    assert launch_store.path.read_bytes() == launch_before
    assert source.read_bytes() == source_before


async def test_breakpoint_restore_shows_error_and_preserves_corrupt_bytes(
    monkeypatch, tmp_path
):
    app, roots, _ = debug_app(monkeypatch, tmp_path)
    state = tmp_path / '.debugpilot' / 'projects' / 'breakpoints.json'
    state.parent.mkdir(parents=True)
    state.write_bytes(b'{broken')
    before = state.read_bytes()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        browser = app.query_one(SourceBrowser)
        assert browser.open_source(roots[0], roots[0] / 'main.py', 1)
        await pilot.click('#source-breakpoint')
        assert 'breakpoint' in rendered(app, '#source-status').lower()
        assert state.read_bytes() == before


async def test_breakpoint_write_failure_keeps_ui_responsive_without_saved_claim(
    monkeypatch, tmp_path
):
    app, roots, _ = debug_app(monkeypatch, tmp_path)
    state = tmp_path / '.debugpilot' / 'projects' / 'breakpoints.json'

    def fail_save(_store, _marks, _options=None, _disabled=None):
        raise ConfigurationError(
            "Cannot save Code breakpoints; check the projects directory permissions."
        )

    monkeypatch.setattr(BreakpointStore, 'save', fail_save)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        browser = await mark(pilot, app, 4)
        assert browser.breakpoints(roots[0], roots[0] / 'main.py') == (4,)
        assert 'Cannot save Code breakpoints' in rendered(app, '#source-status')
        assert not state.exists()
