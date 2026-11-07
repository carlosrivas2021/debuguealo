"""F5 resumes the selected paused debug session and otherwise keeps its run meaning."""

import asyncio

import pytest
from test_code_debug_ui import FakeDebug, debug_app, mark, rendered, until
from textual.widgets import DataTable

from debugpilot.tui import code_debug


class CountingDebug(FakeDebug):
    def __init__(self, on_event, on_output):
        super().__init__(on_event, on_output)
        self.continued = 0

    async def continue_execution(self):
        self.continued += 1
        self.state = 'running'
        self.emit('state', state='running')


@pytest.fixture
def fake_app(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    CountingDebug.instances = FakeDebug.instances = []
    CountingDebug.gate = CountingDebug.failure = None
    monkeypatch.setattr(code_debug, 'PythonDebugSession', CountingDebug)
    return app, roots, store


async def paused_session(pilot, app, row=0):
    app.query_one('#code-projects', DataTable).move_cursor(row=row)
    await pilot.pause()
    count = len(CountingDebug.instances)
    await pilot.press('shift+f5')
    await until(pilot, lambda: len(CountingDebug.instances) == count + 1)
    session = CountingDebug.instances[-1]
    await until(pilot, lambda: session.state == 'stopped')
    return session


async def test_f5_continues_paused_session_without_starting_a_run(fake_app):
    app, _, _ = fake_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        session = await paused_session(pilot, app)

        await pilot.press('f5')
        await until(pilot, lambda: session.continued == 1)

        assert session.state == 'running'
        assert 'Debug running' in rendered(app, '#code-run-state')
        assert not app.query_one('#code-terminal').contexts
        assert app.query_one('#code-debug').display


async def test_f5_while_debug_is_running_does_not_resume_or_start_a_run(fake_app):
    app, _, _ = fake_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        session = await paused_session(pilot, app)
        await pilot.press('f5')
        await until(pilot, lambda: session.continued == 1)

        await pilot.press('f5')
        await pilot.pause()

        assert session.continued == 1
        assert not app.query_one('#code-terminal').contexts


async def test_f5_continues_only_the_profile_under_the_cursor(fake_app):
    app, _, _ = fake_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        first = await paused_session(pilot, app, row=0)
        second = await paused_session(pilot, app, row=1)

        await pilot.press('f5')
        await until(pilot, lambda: second.continued == 1)

        assert first.continued == 0
        assert first.state == 'stopped'


async def test_f5_on_another_idle_profile_runs_it_and_leaves_the_pause(fake_app, monkeypatch):
    app, roots, _ = fake_app
    started = []
    async with app.run_test(size=(120, 45)) as pilot:
        workspace = app.query_one('#code-workspace')

        async def run(profile):
            started.append(profile.root)

        monkeypatch.setattr(workspace, '_start', run)
        await pilot.click('#area-code')
        paused = await paused_session(pilot, app, row=0)
        app.query_one('#code-projects', DataTable).move_cursor(row=1)
        await pilot.pause()

        await pilot.press('f5')
        await until(pilot, lambda: bool(started))

        assert started == [roots[1]]
        assert paused.continued == 0
        assert paused.state == 'stopped'


async def slow_until(pilot, condition):
    # A real debugpy adapter needs longer than the shared helper's deadline.
    async with asyncio.timeout(30):
        while not condition():
            await pilot.pause(0.05)


async def test_real_python_f5_continues_to_exit(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await mark(pilot, app, line=4)
        await pilot.press('shift+f5')
        debug = app.query_one('#code-debug')
        await slow_until(
            pilot, lambda: debug.session is not None and debug.session.state == 'stopped')

        await pilot.press('f5')

        await slow_until(pilot, lambda: 'Exited: 0' in rendered(app, '#code-run-state'))
        assert not app.query_one('#code-terminal').contexts
