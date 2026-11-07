"""Python attach connects to an existing debugpy endpoint without owning its target."""

import asyncio
import json
import os
import socket
import sys

import pytest
from test_code_debug_ui import debug_app, rendered, until
from test_go_attach import DAPPeer
from test_go_attach_ui import FakeGoAttach
from textual.widgets import DataTable

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.debugger import DebugError, GoAttachSession, PythonAttachSession
from debugpilot.storage.code_projects import CodeProject, CodeProjectStore, RemoteAttach
from debugpilot.tui import code_debug

TARGET = '''\
import pathlib
import sys
import time


def work(value):
    total = value + 1
    return total


progress = pathlib.Path(sys.argv[1])
count = 0
while True:
    count = work(count)
    progress.write_text(str(count), encoding='utf-8')
    time.sleep(0.02)
'''
BREAKPOINT_LINE = 7


def attach_profile(root, port, remote_root='/app'):
    return CodeProject('Python attach', root, (),
                       python_attach=RemoteAttach('127.0.0.1', port, remote_root))


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'debugpilot.storage.code_projects.config_path', lambda: tmp_path / 'config.toml')
    result = CodeProjectStore()
    result.ensure_launch_file()
    return result


def write_profile(store, tmp_path, **fields):
    store.path.write_text(json.dumps({'version': 1, 'configurations': [{
        'name': 'Python remote', 'workspaceFolder': str(tmp_path), **fields,
    }]}), encoding='utf-8')


def test_python_attach_profile_needs_no_command(store, tmp_path):
    write_profile(store, tmp_path, pythonAttach={
        'host': '127.0.0.1', 'port': 5678, 'remoteRoot': '/app'})

    profile = store.profiles()[0]

    assert profile.command == ()
    assert profile.go_attach is None
    assert profile.python_attach == RemoteAttach('127.0.0.1', 5678, '/app')
    assert profile.attach == profile.python_attach


@pytest.mark.parametrize('attach', [
    {},
    {'host': 'localhost', 'port': 5678, 'remoteRoot': '/app'},
    {'host': '0.0.0.0', 'port': 5678, 'remoteRoot': '/app'},
    {'host': '127.0.0.1', 'port': True, 'remoteRoot': '/app'},
    {'host': '127.0.0.1', 'port': 5678, 'remoteRoot': 'app'},
    {'host': '127.0.0.1', 'port': 5678, 'remoteRoot': '/app/../etc'},
    {'host': '127.0.0.1', 'port': 5678, 'remoteRoot': '/app', 'extra': 1},
])
def test_invalid_python_attach_is_rejected_naming_the_field(store, tmp_path, attach):
    write_profile(store, tmp_path, pythonAttach=attach)

    with pytest.raises(ConfigurationError, match='Invalid pythonAttach'):
        store.profiles()


def test_profile_cannot_declare_both_attach_kinds(store, tmp_path):
    attach = {'host': '127.0.0.1', 'port': 5678, 'remoteRoot': '/app'}
    write_profile(store, tmp_path, goAttach=attach, pythonAttach=attach)

    with pytest.raises(ConfigurationError, match='either goAttach or pythonAttach'):
        store.profiles()


async def test_attach_request_is_debugpy_shaped_and_paths_are_remote(tmp_path):
    peer = DAPPeer()
    await peer.start()
    source = tmp_path / 'app' / 'main.py'
    source.parent.mkdir()
    source.write_text('pass\n', encoding='utf-8')
    session = PythonAttachSession(timeout=2)
    try:
        await session.start(attach_profile(tmp_path, peer.port), {source: [1]})
        initialize = next(r for r in peer.requests if r['command'] == 'initialize')['arguments']
        attach = next(r for r in peer.requests if r['command'] == 'attach')['arguments']
        breakpoint_request = next(
            r for r in peer.requests if r['command'] == 'setBreakpoints')['arguments']
        assert initialize['adapterID'] == 'python'
        assert attach == {'name': 'Python attach', 'type': 'debugpy', 'request': 'attach',
                          'justMyCode': True, 'subProcess': False}
        assert breakpoint_request['source']['path'] == '/app/app/main.py'
        assert session.profile.python_attach == RemoteAttach('127.0.0.1', peer.port, '/app')
    finally:
        await session.close()
        await peer.close()
    assert session.state == 'closed'
    disconnect = next(r for r in peer.requests if r['command'] == 'disconnect')
    assert disconnect['arguments'] == {'terminateDebuggee': False}


async def test_unreachable_endpoint_reports_python_target(tmp_path):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    session = PythonAttachSession(timeout=2)

    with pytest.raises(DebugError, match='Unable to attach to Python/debugpy'):
        await session.start(attach_profile(tmp_path, port), {})

    assert session.state == 'closed'


async def test_python_session_rejects_go_only_profile(tmp_path):
    profile = CodeProject('Go', tmp_path, (), None, RemoteAttach('127.0.0.1', 2345, '/app'))

    with pytest.raises(DebugError, match='Invalid pythonAttach'):
        await PythonAttachSession(timeout=2).start(profile, {})


async def test_go_session_still_reports_go_target(tmp_path):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    profile = CodeProject('Go', tmp_path, (), None, RemoteAttach('127.0.0.1', port, '/app'))

    with pytest.raises(DebugError, match='Unable to attach to Go/Delve'):
        await GoAttachSession(timeout=2).start(profile, {})


async def next_state(session, wanted):
    async with asyncio.timeout(15):
        while session.state != wanted:
            await session.events.get()


async def wait_for_progress(progress, previous):
    async with asyncio.timeout(15):
        while True:
            text = await asyncio.to_thread(progress.read_text, encoding='utf-8')
            if text and int(text) > previous:
                return int(text)
            await asyncio.sleep(0.02)


async def attach_when_listening(profile, breakpoints):
    # A throwaway probe connection would end debugpy's adapter, so retry the real attach.
    async with asyncio.timeout(15):
        while True:
            session = PythonAttachSession(timeout=15)
            try:
                await session.start(profile, breakpoints)
                return session
            except DebugError:
                await asyncio.sleep(0.05)


@pytest.mark.integration
@pytest.mark.skipif(os.name == 'nt', reason='the remote root must be a POSIX path')
async def test_real_debugpy_breaks_maps_steps_detaches_and_reattaches(tmp_path):
    pytest.importorskip('debugpy')
    remote, local = tmp_path.resolve() / 'remote', tmp_path.resolve() / 'local'
    remote.mkdir()
    local.mkdir()
    (remote / 'target.py').write_text(TARGET, encoding='utf-8')
    source = local / 'target.py'
    source.write_text(TARGET, encoding='utf-8')
    progress = tmp_path / 'progress'
    progress.write_text('', encoding='utf-8')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    target = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'debugpy', '--listen', f'127.0.0.1:{port}', '--wait-for-client',
        str(remote / 'target.py'), str(progress),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    profile = attach_profile(local, port, str(remote))
    try:
        session = await attach_when_listening(profile, {source: [BREAKPOINT_LINE]})
        await next_state(session, 'stopped')
        assert session.verified_breakpoints[str(source)][0]['verified'] is True

        frames = await session.stack()
        assert frames[0]['source']['path'] == str(source)
        assert frames[0]['line'] == BREAKPOINT_LINE
        scopes = await session.scopes(frames[0]['id'])
        names = {v['name'] for v in await session.variables(scopes[0]['variablesReference'])}
        assert 'value' in names

        await session.step_over()
        await next_state(session, 'stopped')
        assert (await session.stack())[0]['line'] == BREAKPOINT_LINE + 1

        # Disconnecting while paused must leave the target running without breakpoints.
        await session.close()
        assert session.state == 'closed'
        assert session.disconnect_warning is None
        reached = await wait_for_progress(progress, 0)
        await wait_for_progress(progress, reached)
        assert target.returncode is None

        reattached = await attach_when_listening(profile, {source: [BREAKPOINT_LINE]})
        await next_state(reattached, 'stopped')
        assert (await reattached.stack())[0]['source']['path'] == str(source)
        await reattached.close()
        assert target.returncode is None
    finally:
        target.kill()
        await target.wait()


@pytest.fixture
async def python_attach_app(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding='utf-8'))
    profile = config['configurations'][0]
    profile.pop('command', None)
    profile['pythonAttach'] = {'host': '127.0.0.1', 'port': 5678, 'remoteRoot': '/app'}
    store.path.write_text(json.dumps(config), encoding='utf-8')
    FakeGoAttach.instances = []
    monkeypatch.setattr(code_debug, 'PythonAttachSession', FakeGoAttach, raising=False)
    return app, roots, store


async def test_shift_f5_dispatches_python_attach_and_stop_only_disconnects(python_attach_app):
    app, roots, _ = python_attach_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await until(pilot, lambda: bool(FakeGoAttach.instances))
        session = FakeGoAttach.instances[0]
        assert session.profile.python_attach.port == 5678
        assert session.profile.root == roots[0]
        assert 'Attached' in rendered(app, '#code-run-state')
        assert app.query_one('#code-stop').label == 'Disconnect'
        assert not app.query_one('#code-terminal').active

        await pilot.click('#code-stop')

        assert session.closed
        state = rendered(app, '#code-run-state')
        assert 'Disconnected' in state
        assert 'Exited' not in state


async def test_unexpected_python_disconnect_offers_explicit_reconnect(python_attach_app):
    app, _, _ = python_attach_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await until(pilot, lambda: bool(FakeGoAttach.instances))

        session = FakeGoAttach.instances[0]
        session.emit('transportClosed', message='lost')
        session.state = 'closed'
        session.emit('state', state='closed')
        await pilot.pause()

        assert 'target state UNKNOWN' in rendered(app, '#code-run-state')
        assert app.query_one('#code-reconnect').display


async def test_endpoint_is_exclusive_across_attach_kinds(python_attach_app, monkeypatch):
    app, _, store = python_attach_app
    config = json.loads(store.path.read_text(encoding='utf-8'))
    second = config['configurations'][1]
    second.pop('command', None)
    second['goAttach'] = {'host': '127.0.0.1', 'port': 5678, 'remoteRoot': '/app'}
    store.path.write_text(json.dumps(config), encoding='utf-8')
    monkeypatch.setattr(code_debug, 'GoAttachSession', FakeGoAttach)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await until(pilot, lambda: len(FakeGoAttach.instances) == 1)
        app.query_one('#code-projects', DataTable).move_cursor(row=1)
        await pilot.pause()
        app.action_debug_code()
        await pilot.pause()

        assert len(FakeGoAttach.instances) == 1
        assert 'endpoint 127.0.0.1:5678 is already active' in rendered(app, '#code-run-state')
