"""Node attach connects to an existing loopback Inspector without owning its process."""

import asyncio
import contextlib
import json
import os
import re
import shutil
import socket

import pytest
from test_code_debug_ui import debug_app, rendered, until
from test_go_attach_ui import FakeGoAttach

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.debugger import DebugError, NodeAttachSession
from debugpilot.storage.code_projects import CodeProject, CodeProjectStore, RemoteAttach
from debugpilot.tui import code_debug

TARGET = '''\
const fs = require('fs');
function work(value) {
  const total = value + 1;
  return total;
}
let count = 0;
setInterval(() => {
  count = work(count);
  fs.writeFileSync(process.argv[2], String(count));
}, 20);
'''
BREAKPOINT_LINE = 3
ATTACH = {'host': '127.0.0.1', 'port': 9229, 'remoteRoot': '/app'}


def attach_profile(root, port, remote_root='/app'):
    return CodeProject('Node attach', root, (),
                       node_attach=RemoteAttach('127.0.0.1', port, remote_root))


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'debugpilot.storage.code_projects.config_path', lambda: tmp_path / 'config.toml')
    result = CodeProjectStore()
    result.ensure_launch_file()
    return result


def write_profile(store, tmp_path, **fields):
    store.path.write_text(json.dumps({'version': 1, 'configurations': [{
        'name': 'Node remote', 'workspaceFolder': str(tmp_path), **fields,
    }]}), encoding='utf-8')


def free_port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        return reservation.getsockname()[1]


def test_node_attach_profile_needs_no_command(store, tmp_path):
    write_profile(store, tmp_path, nodeAttach=ATTACH)

    profile = store.profiles()[0]

    assert profile.command == ()
    assert profile.go_attach is None
    assert profile.python_attach is None
    assert profile.node_attach == RemoteAttach('127.0.0.1', 9229, '/app')
    assert profile.attach == profile.node_attach


@pytest.mark.parametrize('attach', [
    {},
    {'host': 'localhost', 'port': 9229, 'remoteRoot': '/app'},
    {'host': '127.0.0.1', 'port': 0, 'remoteRoot': '/app'},
    {'host': '127.0.0.1', 'port': 9229, 'remoteRoot': 'app'},
    {'host': '127.0.0.1', 'port': 9229, 'remoteRoot': '/app/../etc'},
    {'host': '127.0.0.1', 'port': 9229, 'remoteRoot': '/app', 'extra': 1},
])
def test_invalid_node_attach_is_rejected_naming_the_field(store, tmp_path, attach):
    write_profile(store, tmp_path, nodeAttach=attach)

    with pytest.raises(ConfigurationError, match='Invalid nodeAttach'):
        store.profiles()


@pytest.mark.parametrize('other', ['goAttach', 'pythonAttach'])
def test_node_attach_excludes_other_attach_kinds(store, tmp_path, other):
    write_profile(store, tmp_path, nodeAttach=ATTACH, **{other: ATTACH})

    with pytest.raises(ConfigurationError,
                       match='use only one of goAttach, pythonAttach or nodeAttach'):
        store.profiles()


def test_node_attach_rejects_env_like_other_attach_kinds(store, tmp_path):
    write_profile(store, tmp_path, nodeAttach=ATTACH, env={'A': '1'})

    with pytest.raises(ConfigurationError, match='an attach target keeps the environment'):
        store.profiles()


async def test_node_session_rejects_profile_without_node_attach(tmp_path):
    profile = CodeProject('Go', tmp_path, (), None, RemoteAttach('127.0.0.1', 2345, '/app'))

    with pytest.raises(DebugError, match='Invalid nodeAttach'):
        await NodeAttachSession(timeout=2).start(profile, {})


async def test_unreachable_endpoint_reports_node_target(tmp_path):
    session = NodeAttachSession(timeout=2)

    with pytest.raises(DebugError, match='Unable to attach to Node/Inspector'):
        await session.start(attach_profile(tmp_path, free_port()), {})

    assert session.state == 'closed'


@pytest.mark.parametrize('body', [
    b'not json',
    pytest.param(b'[' * 30000 + b']' * 30000, id='deeply-nested'),
    b'[]',
    b'[{"type": "node"}]',
    b'[{"type": "node", "webSocketDebuggerUrl": "ws://10.0.0.1:9229/abc"}]',
])
async def test_endpoint_without_one_loopback_inspector_target_is_rejected(tmp_path, body):
    async def respond(reader, writer):
        await reader.readuntil(b'\r\n\r\n')
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                     + f'Content-Length: {len(body)}\r\n\r\n'.encode() + body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(respond, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    session = NodeAttachSession(timeout=2)
    try:
        with pytest.raises(DebugError, match='Unable to attach to Node/Inspector'):
            await session.start(attach_profile(tmp_path, port), {})
    finally:
        server.close()
        await server.wait_closed()
    assert session.state == 'closed'


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


async def start_inspected_node(script, progress):
    target = await asyncio.create_subprocess_exec(
        'node', '--inspect=127.0.0.1:0', str(script), str(progress),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(15):
        while True:
            line = (await target.stderr.readline()).decode()
            match = re.match(r'Debugger listening on ws://127\.0\.0\.1:(\d+)/', line)
            if match:
                break
            if not line:
                raise AssertionError('node exited before its Inspector listened')

    async def drain():
        while await target.stderr.readline():
            pass

    return target, int(match[1]), asyncio.create_task(drain())


@pytest.mark.integration
@pytest.mark.skipif(shutil.which('node') is None, reason='needs the node runtime')
@pytest.mark.skipif(os.name == 'nt', reason='the remote root must be a POSIX path')
async def test_real_node_breaks_maps_steps_detaches_and_reattaches(tmp_path):
    remote, local = tmp_path.resolve() / 'remote', tmp_path.resolve() / 'local'
    remote.mkdir()
    local.mkdir()
    (remote / 'target.js').write_text(TARGET, encoding='utf-8')
    source = local / 'target.js'
    source.write_text(TARGET, encoding='utf-8')
    progress = tmp_path / 'progress'
    progress.write_text('', encoding='utf-8')
    target, port, drain = await start_inspected_node(remote / 'target.js', progress)
    profile = attach_profile(local, port, str(remote))
    try:
        session = NodeAttachSession(timeout=15)
        await session.start(profile, {source: [BREAKPOINT_LINE]})
        assert session.profile.node_attach == RemoteAttach('127.0.0.1', port, str(remote))
        await next_state(session, 'stopped')
        assert session.verified_breakpoints[str(source)][0]['verified'] is True

        frames = await session.stack()
        assert frames[0]['source']['path'] == str(source)
        assert frames[0]['line'] == BREAKPOINT_LINE
        scopes = await session.scopes(frames[0]['id'])
        values = {v['name']: v['value'] for scope in scopes if not scope['expensive']
                  for v in await session.variables(scope['variablesReference'])}
        assert 'value' in values
        assert await session.evaluate('value + 100', frames[0]['id']) == str(
            int(values['value']) + 100)

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

        reattached = NodeAttachSession(timeout=15)
        await reattached.start(profile, {source: [BREAKPOINT_LINE]})
        await next_state(reattached, 'stopped')
        assert (await reattached.stack())[0]['source']['path'] == str(source)
        await reattached.close()
        reached = await wait_for_progress(progress, 0)
        await wait_for_progress(progress, reached)
        assert target.returncode is None
    finally:
        target.kill()
        await target.wait()
        drain.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await drain


@pytest.fixture
async def node_attach_app(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding='utf-8'))
    profile = config['configurations'][0]
    profile.pop('command', None)
    profile['nodeAttach'] = ATTACH
    store.path.write_text(json.dumps(config), encoding='utf-8')
    FakeGoAttach.instances = []
    monkeypatch.setattr(code_debug, 'NodeAttachSession', FakeGoAttach, raising=False)
    return app, roots, store


async def test_shift_f5_dispatches_node_attach_and_stop_only_disconnects(node_attach_app):
    app, roots, _ = node_attach_app
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('shift+f5')
        await until(pilot, lambda: bool(FakeGoAttach.instances))
        session = FakeGoAttach.instances[0]
        assert session.profile.node_attach.port == 9229
        assert session.profile.root == roots[0]
        assert 'Attached' in rendered(app, '#code-run-state')
        assert app.query_one('#code-stop').label == 'Disconnect'

        await pilot.click('#code-stop')

        assert session.closed
        state = rendered(app, '#code-run-state')
        assert 'Disconnected' in state
        assert 'Exited' not in state


@pytest.mark.integration
@pytest.mark.skipif(shutil.which('node') is None, reason='needs the node runtime')
async def test_target_exit_closes_session_as_lost_without_cleanup_warning(tmp_path):
    script = tmp_path / 'target.js'
    script.write_text(TARGET, encoding='utf-8')
    progress = tmp_path / 'progress'
    target, port, drain = await start_inspected_node(script, progress)
    events = []
    session = NodeAttachSession(on_event=events.append, timeout=15)
    try:
        await session.start(attach_profile(tmp_path, port, str(tmp_path.resolve())), {})
        assert session.state == 'running'
        target.kill()
        await target.wait()
        await next_state(session, 'closed')
        assert any(e.get('event') == 'transportClosed' for e in events)
        assert session.disconnect_warning is None
    finally:
        await session.close()
        if target.returncode is None:
            target.kill()
            await target.wait()
        drain.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await drain


async def test_non_numeric_content_length_is_reported_as_not_an_inspector(tmp_path):
    async def respond(reader, writer):
        await reader.readuntil(b'\r\n\r\n')
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: abc\r\n\r\n[]')
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(respond, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(DebugError, match='did not answer as a Node Inspector$'):
            await NodeAttachSession(timeout=2).start(attach_profile(tmp_path, port), {})
    finally:
        server.close()
        await server.wait_closed()
