"""Public Code TUI debugging, including a real adapter (never silently skipped)."""

import asyncio
import json
import sys

import pytest
from test_code_project_store import configure
from test_source_browser import BrowserApp
from test_tui_grouping import Docker, until
from textual.screen import ModalScreen
from textual.widgets import DataTable, TextArea, Tree

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.debugger import DebugError
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.source_browser import SourceBrowser


def debug_app(monkeypatch, tmp_path):
    store = configure(monkeypatch, tmp_path)
    roots = [tmp_path / 'one', tmp_path / 'two']
    for root in roots:
        root.mkdir()
        (root / 'main.py').write_text(
            'def increment(value):\n    return value + 1\n'
            'answer = 41\nanswer = increment(answer)\nprint(f"RESULT:{answer}")\n',
            encoding='utf-8',
        )
    store.path.write_text(json.dumps({'version': 1, 'configurations': [
        {'name': root.name, 'workspaceFolder': str(root),
         'command': [sys.executable, '-u', 'main.py']} for root in roots
    ]}), encoding='utf-8')
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    return app, roots, store


async def mark(pilot, app, line=4):
    browser = app.query_one(SourceBrowser)
    tree = browser.query_one(Tree)
    tree.select_node(next(n for n in tree.root.children if str(n.label) == 'main.py'))
    await pilot.pause()
    browser.query_one(TextArea).move_cursor((line - 1, 0))
    await pilot.click('#source-breakpoint')
    return browser


def rendered(app, selector):
    return str(app.query_one(selector).render())


async def test_real_shift_f5_breakpoint_inspection_steps_continue_and_attribution(
    monkeypatch, tmp_path
):
    from debugpilot.tui import code_debug

    stopped = asyncio.Event()
    session_type = code_debug.PythonDebugSession

    def observed_session(*, on_event, on_output):
        def observe(message):
            on_event(message)
            if message.get('event') == 'stopped':
                stopped.set()

        return session_type(on_event=observe, on_output=on_output)

    monkeypatch.setattr(code_debug, 'PythonDebugSession', observed_session)
    app, roots, store = debug_app(monkeypatch, tmp_path)
    original = store.path.read_bytes()

    async def expect_pause(pilot, value):
        # A real adapter may spend up to 15s starting. Observe the public stopped
        # event and its rendered inspection, not the generic 3s inventory deadline.
        async with asyncio.timeout(15):
            await stopped.wait()
            while not (
                'Debug stopped: one' in rendered(app, '#code-run-state')
                and value in rendered(app, '#code-variables')
            ):
                assert 'Unable to debug' not in rendered(app, '#code-run-state')
                await pilot.pause(0.02)

    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click('#area-code')
        browser = await mark(pilot, app)
        await pilot.press('shift+f5')  # Source focus must not suppress launching.
        await expect_pause(pilot, 'answer = 41')
        assert '41' in rendered(app, '#code-variables')
        stack = app.query_one('#code-stack', DataTable)
        assert stack.row_count >= 1
        assert browser.query_one(TextArea).cursor_location[0] == 3
        assert '▶' in browser.query_one(TextArea).render_line(3).text
        assert 'verified' in str(browser.query_one(Tree).root.children[0].children[0].label)
        assert browser.breakpoints(roots[0], roots[0] / 'main.py') == (4,)
        profiles = app.query_one('#code-projects', DataTable)
        profiles.focus()
        await pilot.press('shift+f5')  # Must not launch a second execution.
        profiles.move_cursor(row=1)
        await pilot.pause()
        await pilot.click('#area-containers')
        await pilot.press('f10')  # Containers must not step the hidden Code debugger.
        await pilot.click('#area-code')
        # Keyboard controls now belong to the selected profile context; return to
        # the running profile before stepping rather than controlling it from row two.
        profiles.move_cursor(row=0)
        await pilot.pause()
        stopped.clear()
        await pilot.press('f11')
        await expect_pause(pilot, 'value = 41')
        assert browser.root_path == roots[0].resolve()
        assert browser.file_path == (roots[0] / 'main.py').resolve()
        stopped.clear()
        await pilot.press('shift+f11')
        await expect_pause(pilot, 'answer')
        stopped.clear()
        await pilot.press('f10')
        await expect_pause(pilot, 'answer = 42')
        await pilot.click('#code-continue')
        await until(pilot, lambda: 'Exited: 0' in rendered(app, '#code-run-state'))
        output = '\n'.join(line.text for line in app.query_one('#code-debug-output').lines)
        assert 'RESULT:42' in output
        assert '[one · stderr]' not in output
        assert 'one' in rendered(app, '#code-run-state')
        assert stack.row_count == 0
        assert 'answer' not in rendered(app, '#code-variables')
        assert browser.breakpoints(roots[0], roots[0] / 'main.py') == (4,)
        assert store.path.read_bytes() == original
        await pilot.click('#code-stop')
    assert store.path.read_bytes() == original


class FakeDebug:
    instances = []
    gate = None
    failure = None

    def __init__(self, on_event, on_output):
        self.events = asyncio.Queue()
        self.on_event, self.on_output = on_event, on_output
        self.state = 'idle'
        self.exit_code = None
        self.verified_breakpoints = {}
        self.requested_breakpoints = {}
        self.closed = False
        self.updates = []
        self.instances.append(self)

    def emit(self, name, **body):
        message = {'event': name, 'body': body}
        self.events.put_nowait(message)
        self.on_event(message)

    async def start(self, profile, marks):
        self.profile, self.marks = profile, marks
        self.requested_breakpoints = dict(marks)
        self.state = 'starting'
        self.emit('state', state='starting')
        if self.gate is not None:
            await self.gate.wait()
        if self.failure:
            raise DebugError(self.failure)
        self.state = 'stopped'
        self.emit('state', state='stopped')
        self.emit('stopped', threadId=1)  # Deliberately before start returns.

    async def stack(self):
        return [{'id': 1, 'name': 'main', 'line': 4,
                 'source': {'path': str(self.profile.root / 'main.py')}}]

    async def scopes(self, frame):
        return [{'name': 'Locals', 'variablesReference': 1}]

    async def variables(self, reference):
        return [{'name': 'answer', 'value': '41', 'variablesReference': 0}]

    async def set_breakpoints(self, path, lines):
        self.updates.append((path, tuple(lines)))
        self.requested_breakpoints[path] = tuple(lines)
        result = [{'verified': False, 'line': line + 1} for line in lines]
        self.verified_breakpoints[path] = result
        return result

    async def close(self):
        self.closed = True
        self.state = 'closed'
        self.emit('state', state='closed')


@pytest.fixture
def fake(monkeypatch):
    from debugpilot.tui import code_debug
    monkeypatch.setattr(FakeDebug, 'instances', [])
    monkeypatch.setattr(FakeDebug, 'gate', None)
    monkeypatch.setattr(FakeDebug, 'failure', None)
    monkeypatch.setattr(code_debug, 'PythonDebugSession', FakeDebug)
    return FakeDebug


async def test_stop_cancels_startup_shutdown_and_rejects_late_callbacks(
    monkeypatch, tmp_path, fake
):
    fake.gate = asyncio.Event()
    app, roots, store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await until(pilot, lambda: len(fake.instances) == 1)
        session = fake.instances[0]
        await pilot.press('shift+f5', 'f5')
        assert len(fake.instances) == 1
        await pilot.click('#code-stop')
        assert session.closed
        assert session.events.empty()
        await app.query_one('#code-workspace').stop()
        session.on_output('stdout', 'OBSOLETE')
        session.emit('stopped', threadId=1)
        await pilot.pause()
        assert 'Stopped' in rendered(app, '#code-run-state')
        assert app.query_one('#code-stack', DataTable).row_count == 0
        assert 'OBSOLETE' not in str(app.query_one('#code-debug-output').lines)
        app.query_one('#code-projects').focus()
        await pilot.press('shift+f5')
        await until(pilot, lambda: len(fake.instances) == 2)
    assert all(session.closed for session in fake.instances)


async def test_early_stop_event_breakpoint_updates_keep_original_root_and_intent(
    monkeypatch, tmp_path, fake
):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        browser = await mark(pilot, app)
        await pilot.press('shift+f5')
        await until(pilot, lambda: 'answer' in rendered(app, '#code-variables'))
        session = fake.instances[0]
        assert session.marks == {str((roots[0] / 'main.py').resolve()): (4,)}
        assert session.events.empty()
        app.query_one('#code-projects', DataTable).move_cursor(row=1)
        await pilot.pause()
        await mark(pilot, app, 3)
        assert not session.updates
        app.query_one('#code-projects', DataTable).move_cursor(row=0)
        await pilot.pause()
        await mark(pilot, app, 4)  # Remove original line, never relocate requested intent.
        await until(pilot, lambda: bool(session.updates))
        assert session.updates[-1] == (str((roots[0] / 'main.py').resolve()), ())
        assert browser.breakpoints(roots[0], roots[0] / 'main.py') == ()
        await pilot.pause(0.3)
        await mark(pilot, app, 4)
        await until(pilot, lambda: session.updates[-1][1] == (4,))
        assert browser.breakpoints(roots[0], roots[0] / 'main.py') == (4,)
        label = str(browser.query_one(Tree).root.children[0].children[0].label)
        assert 'unverified' in label and 'Line 5' in label
        assert '●' in browser.query_one(TextArea).render_line(3).text
        await pilot.click('#code-stop')
        session.on_output('stdout', 'late')
        session.emit('stopped', threadId=1)
        await pilot.pause()
        assert 'Stopped' in rendered(app, '#code-run-state')
        assert app.query_one('#code-stack', DataTable).row_count == 0


async def test_debug_error_actionable_without_fallback_or_config_change(
    monkeypatch, tmp_path, fake
):
    fake.failure = 'Install debugpy in the selected interpreter. No run-mode fallback.'
    app, roots, store = debug_app(monkeypatch, tmp_path)
    original = store.path.read_bytes()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await until(pilot, lambda: 'Install debugpy' in rendered(app, '#code-run-state'))
        assert not app.query_one('#code-terminal').active
        assert fake.instances[0].closed
        assert store.path.read_bytes() == original


async def test_debug_navigation_uses_safe_preview_and_snapshot_is_independent(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    source = root / 'main.py'
    source.write_text('answer = 41\n', encoding='utf-8')
    outside = tmp_path / 'outside.py'
    outside.write_text('SECRET', encoding='utf-8')
    app = BrowserApp()
    async with app.run_test() as pilot:
        browser = app.query_one(SourceBrowser)
        assert browser.open_source(root, source, 1)
        await pilot.click('#source-breakpoint')
        snapshot = browser.breakpoint_snapshot(root)
        snapshot.clear()
        assert browser.breakpoints(root, source) == (1,)
        assert not browser.open_source(root, outside, 1)
        assert browser.query_one(TextArea).text == ''
        assert 'outside the selected project' in rendered(app, '#source-status')
        source.write_bytes(b'x' * (1024 * 1024 + 1))
        assert not browser.open_source(root, source, 1)
        assert '1 MiB' in rendered(app, '#source-status')
        source.write_bytes(b'\xff')
        assert not browser.open_source(root, source, 1)
        assert browser.query_one(TextArea).text == ''


async def test_debug_navigation_rejects_directory_links_and_root_links(tmp_path):
    import os

    target = tmp_path / 'target'
    target.mkdir()
    (target / 'main.py').write_text('DO NOT PREVIEW', encoding='utf-8')
    root = tmp_path / 'root'
    root.mkdir()
    link = root / 'linked'
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    app = BrowserApp()
    async with app.run_test():
        browser = app.query_one(SourceBrowser)
        assert not browser.open_source(root, link / 'main.py', 1)
        assert browser.query_one(TextArea).text == ''
        # Even a root link must not be resolved into an implicitly trusted project.
        assert not browser.open_source(link, link / 'main.py', 1)
        assert browser.query_one(TextArea).text == ''
        assert not browser.open_source(link, target / 'main.py', 1)
        assert browser.query_one(TextArea).text == ''


async def test_code_shortcut_modal_terminal_and_container_guards(monkeypatch, tmp_path, fake):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        selected = app.selected_container
        await pilot.press('shift+f5', 'f10', 'f11', 'shift+f11')
        assert not fake.instances
        await pilot.click('#area-code')
        for action in ('open_container_terminal', 'open_host_terminal', 'stop_selected',
                       'recreate_selected', 'toggle_compose_output'):
            assert app.check_action(action, ()) is False
        modal = ModalScreen()
        await app.push_screen(modal)
        await pilot.press('shift+f5', 'f10', 'f11', 'shift+f11', 'f5')
        assert not fake.instances
        modal.dismiss()
        await pilot.pause()
        app.query_one('#code-terminal').focus()
        await pilot.pause()
        # An inactive terminal no longer owns the keys (a live one still does; see
        # test_code_rerun_focus.py), so Code shortcuts stay available from it.
        assert not app.query_one('#code-terminal').active
        assert app.check_action('debug_code', ()) is not False
        assert app.check_action('run_code', ()) is not False
        await pilot.click('#area-containers')
        assert app.selected_container == selected


async def test_compact_debug_controls_source_and_inspection_remain_visible(
    monkeypatch, tmp_path, fake
):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await until(pilot, lambda: 'answer' in rendered(app, '#code-variables'))
        for selector in ('#code-stop', '#code-continue', '#code-over', '#code-in',
                         '#code-out', '#source-text', '#code-stack', '#code-debug-output'):
            widget = app.query_one(selector)
            assert widget.region.height > 0
            assert widget.region.y >= 1
            assert widget.region.bottom <= 23, (selector, widget.region)


@pytest.mark.parametrize('command', [['npm', 'run', 'dev'], [sys.executable, '-c', 'pass']])
async def test_unsupported_debug_command_never_falls_back(monkeypatch, tmp_path, command):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding='utf-8'))
    config['configurations'][0]['command'] = command
    store.path.write_text(json.dumps(config), encoding='utf-8')
    original = store.path.read_bytes()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await until(pilot, lambda: 'Supported Python commands' in rendered(app, '#code-run-state'))
        assert not app.query_one('#code-terminal').active
        assert app.query_one('#code-stack', DataTable).row_count == 0
        assert store.path.read_bytes() == original
        assert not app.query_one('#code-run').disabled


async def test_npm_f5_original_argv_shift_f5_explicit_node_target(monkeypatch, tmp_path):
    from debugpilot.tui import code_debug

    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text())
    config['configurations'][0].update(command=['npm', 'run', 'dev'],
                                      nodeDebug=['node', 'server.js', 'literal'])
    store.path.write_text(json.dumps(config))
    original = store.path.read_bytes()
    launched = []

    async def run(profile):
        launched.append(profile.command)

    FakeDebug.instances = []
    FakeDebug.gate = None
    FakeDebug.failure = None
    monkeypatch.setattr(code_debug, 'NodeDebugSession', FakeDebug)
    async with app.run_test(size=(120, 45)) as pilot:
        workspace = app.query_one('#code-workspace')
        monkeypatch.setattr(workspace, '_start', run)
        await pilot.click('#area-code')
        await pilot.press('f5')
        await until(pilot, lambda: bool(launched))
        assert launched == [('npm', 'run', 'dev')]
        await pilot.press('shift+f5')
        await until(pilot, lambda: bool(FakeDebug.instances))
        assert FakeDebug.instances[0].profile.node_debug == ('node', 'server.js', 'literal')
        assert FakeDebug.instances[0].profile.command == ('npm', 'run', 'dev')
        await pilot.click('#code-stop')
        assert FakeDebug.instances[0].closed
        assert store.path.read_bytes() == original


async def test_adapter_stack_path_is_rejected_by_public_preview(monkeypatch, tmp_path, fake):
    outside = tmp_path / 'outside.py'
    outside.write_text('NOT_TRUSTED', encoding='utf-8')

    async def unsafe_stack(self):
        return [{'id': 1, 'name': 'unsafe', 'line': 1, 'source': {'path': str(outside)}}]

    monkeypatch.setattr(fake, 'stack', unsafe_stack)
    app, roots, store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await until(
            pilot, lambda: 'outside the selected project' in rendered(app, '#source-status')
        )
        assert app.query_one(SourceBrowser).file_path is None
        assert app.query_one('#source-text', TextArea).text == ''
        assert outside.read_text(encoding='utf-8') == 'NOT_TRUSTED'


async def test_obsolete_inspection_cannot_repopulate_after_stop_or_new_session(
    monkeypatch, tmp_path, fake
):
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_variables(self, reference):
        entered.set()
        await release.wait()
        return [{'name': 'OBSOLETE', 'value': '41'}]

    monkeypatch.setattr(fake, 'variables', delayed_variables)
    app, roots, store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await asyncio.wait_for(entered.wait(), 3)
        await pilot.click('#code-stop')
        release.set()
        await pilot.pause()
        assert 'OBSOLETE' not in rendered(app, '#code-variables')
        assert app.query_one('#code-stack', DataTable).row_count == 0
        assert app.query_one(SourceBrowser).file_path is None
        fake.failure = 'No run-mode fallback.'
        app.query_one('#code-projects').focus()
        await pilot.press('shift+f5')
        await until(pilot, lambda: len(fake.instances) == 2)
        fake.instances[0].emit('stopped', threadId=1)
        await pilot.pause()
        assert 'OBSOLETE' not in rendered(app, '#code-variables')
