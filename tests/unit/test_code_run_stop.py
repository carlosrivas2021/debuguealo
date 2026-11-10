"""A Code run says it is running, stops with S, and leaves a clear end marker."""

import asyncio

import pytest
from test_code_run_ui import setup_app
from test_tui_grouping import until

SERVICE = "import time; print('READY', flush=True); time.sleep(60)"


def state(app):
    return str(app.query_one('#code-run-state').render())


def text(pane):
    return pane.render().plain


async def test_running_title_and_s_stops_with_a_marker(monkeypatch, tmp_path):
    app = setup_app(monkeypatch, tmp_path, SERVICE)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('f5')
        pane = app.query_one('#code-terminal')
        await until(pilot, lambda: 'READY' in text(pane))
        await until(pilot, lambda: 'running' in str(pane.border_title))
        assert 's stop' in str(pane.border_title)
        app.query_one('#code-projects').focus()
        await pilot.press('s')
        async with asyncio.timeout(10):
            while 'Stopped' not in state(app):
                await pilot.pause(0.05)
        await pilot.pause()
        assert '── Stopped ──' in text(pane)
        assert text(pane).index('READY') < text(pane).index('── Stopped ──')
        # No blinking cursor: nothing is waiting for input any more.
        assert pane._screen.cursor.hidden
        assert str(pane.border_title) == 'Terminal · stopped'
        assert not pane.active


@pytest.mark.parametrize(('code', 'marker'), [(0, '── Exited: 0 ──'), (3, '── Exited: 3 ──')])
async def test_a_program_that_ends_shows_its_exit_code(monkeypatch, tmp_path, code, marker):
    app = setup_app(monkeypatch, tmp_path, f"print('bye', flush=True); raise SystemExit({code})")
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('f5')
        pane = app.query_one('#code-terminal')
        await until(pilot, lambda: f'Exited: {code}' in state(app))
        await pilot.pause()
        assert marker in text(pane)
        assert pane._screen.cursor.hidden
        assert str(pane.border_title) == f'Terminal · exited {code}'


async def test_s_in_a_live_terminal_goes_to_the_program(monkeypatch, tmp_path):
    app = setup_app(monkeypatch, tmp_path, "print('READY', flush=True); input()")
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('f5')
        pane = app.query_one('#code-terminal')
        await until(pilot, lambda: 'READY' in text(pane))
        pane.focus()
        await pilot.pause()
        sent = []
        monkeypatch.setattr(pane._session, 'write', sent.append)
        await pilot.press('s')
        await pilot.pause()
        assert sent == ['s']
        assert pane.active
        await pilot.click('#code-stop')


async def test_footer_shows_s_to_stop_in_code(monkeypatch, tmp_path):
    app = setup_app(monkeypatch, tmp_path, SERVICE)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click('#area-code')
        await pilot.pause()
        keys = {binding.key for (_, binding, enabled, _) in app.active_bindings.values()
                if binding.show and enabled}
        assert 's' in keys
