"""Go attach's public API speaks DAP without owning a target process."""

import asyncio
import json
import os
import shutil
import socket
from pathlib import Path

import pytest

from debugpilot.debugger import DebugError
from debugpilot.storage.code_projects import CodeProject, GoAttach


class DAPPeer:
    def __init__(self):
        self.server = None
        self.port = None
        self.requests = []
        self.connections = 0

    async def start(self):
        self.server = await asyncio.start_server(self._connect, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def close(self):
        self.server.close()
        await self.server.wait_closed()

    async def _connect(self, reader, writer):
        self.connections += 1
        try:
            while True:
                header = await reader.readuntil(b'\r\n\r\n')
                length = int(header.split(b':', 1)[1].strip())
                message = json.loads(await reader.readexactly(length))
                self.requests.append(message)
                command = message['command']
                body = {}
                if command == 'setBreakpoints':
                    requested = message['arguments']['breakpoints']
                    body = {'breakpoints': [
                        {'id': 1, 'verified': True, **item} for item in requested]}
                elif command == 'stackTrace':
                    body = {'stackFrames': [{'id': 7, 'name': 'main.main', 'line': 4,
                                             'source': {'path': '/app/main.go'}}]}
                elif command == 'scopes':
                    body = {'scopes': [{'name': 'Locals', 'variablesReference': 8,
                                        'expensive': False}]}
                elif command == 'variables':
                    body = {'variables': [{'name': 'answer', 'value': '41',
                                           'variablesReference': 0}]}
                await self._send(writer, {'type': 'response', 'request_seq': message['seq'],
                                          'command': command, 'success': True, 'body': body})
                if command == 'attach':
                    await self._send(writer, {'type': 'event', 'event': 'initialized', 'body': {}})
                elif command in {'configurationDone', 'next'}:
                    await self._send(writer, {'type': 'event', 'event': 'stopped',
                                              'body': {'threadId': 1, 'reason': 'breakpoint'}})
                elif command == 'continue':
                    await self._send(writer, {'type': 'event', 'event': 'continued',
                                              'body': {'threadId': 1}})
                elif command == 'disconnect':
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    @staticmethod
    async def _send(writer, message):
        data = json.dumps(message).encode()
        writer.write(f'Content-Length: {len(data)}\r\n\r\n'.encode() + data)
        await writer.drain()


@pytest.fixture
async def peer():
    result = DAPPeer()
    await result.start()
    yield result
    await result.close()


def profile(root, port):
    return CodeProject('Go attach', root, (), None,
                       GoAttach('127.0.0.1', port, '/app'))


async def test_attach_handshake_maps_sources_inspects_steps_and_continues(tmp_path, peer):
    from debugpilot.debugger import GoAttachSession

    source = tmp_path / 'main.go'
    source.write_text('package main\n')
    session = GoAttachSession(timeout=2)
    try:
        await session.start(profile(tmp_path, peer.port), {source: [4]})
        assert session.state == 'stopped'
        attach = next(item for item in peer.requests if item['command'] == 'attach')['arguments']
        assert attach == {'name': 'Go attach', 'type': 'go', 'request': 'attach',
                          'mode': 'remote', 'host': '127.0.0.1', 'port': peer.port,
                          'substitutePath': [{'from': str(tmp_path.resolve()), 'to': '/app'}]}
        request = next(item for item in peer.requests if item['command'] == 'setBreakpoints')
        assert request['arguments']['source']['path'] == '/app/main.go'
        assert (await session.stack())[0]['source']['path'] == str(source.resolve())
        scopes = await session.scopes(7)
        variables = await session.variables(scopes[0]['variablesReference'])
        assert variables == [{'name': 'answer', 'value': '41', 'variablesReference': 0}]
        await session.step_over()
        await session.continue_execution()
        assert [item['command'] for item in peer.requests if item['type'] == 'request'][-2:] == [
            'next', 'continue']
    finally:
        await session.close()
    disconnect = [item for item in peer.requests if item['command'] == 'disconnect'][-1]
    assert disconnect['arguments'] == {'terminateDebuggee': False}
    assert not any(item['command'] in {'terminate', 'launch'} for item in peer.requests)


async def test_disconnect_clears_mapped_sources_then_resumes_without_changing_intent(
        tmp_path, peer):
    from debugpilot.debugger import GoAttachSession

    source = tmp_path / 'main.go'
    source.write_text('package main\n')
    session = GoAttachSession(timeout=2)
    await session.start(profile(tmp_path, peer.port), {source: [4]})
    intent = dict(session.requested_breakpoints)
    await asyncio.gather(session.close(), session.close())

    requests = [item for item in peer.requests if item['type'] == 'request']
    cleanup = [item for item in requests if item['command'] in {
        'setBreakpoints', 'continue', 'disconnect'}]
    assert [item['command'] for item in cleanup] == [
        'setBreakpoints', 'setBreakpoints', 'continue', 'disconnect']
    assert cleanup[0]['arguments']['source']['path'] == '/app/main.go'
    assert cleanup[1]['arguments'] == {
        'source': {'path': '/app/main.go'}, 'breakpoints': [], 'sourceModified': False,
    }
    assert cleanup[2]['arguments'] == {'threadId': 1}
    assert cleanup[3]['arguments'] == {'terminateDebuggee': False}
    assert session.requested_breakpoints == intent == {str(source.resolve()): (4,)}
    assert not any(item['command'] in {'terminate', 'launch'} for item in requests)


async def test_disconnect_and_reconnect_never_terminate_external_target(tmp_path, peer):
    from debugpilot.debugger import GoAttachSession

    session = GoAttachSession(timeout=2)
    target = profile(tmp_path, peer.port)
    await session.start(target, {})
    await session.close()
    await session.start(target, {})
    await session.close()

    assert peer.connections == 2
    disconnects = [item for item in peer.requests if item['command'] == 'disconnect']
    assert len(disconnects) == 2
    assert all(item['arguments'] == {'terminateDebuggee': False} for item in disconnects)
    assert not any(item['command'] in {'terminate', 'launch'} for item in peer.requests)


@pytest.mark.parametrize('remote_root', ['/app/../outside', r'\outside'])
async def test_invalid_direct_remote_root_does_not_connect_or_mutate(tmp_path, peer, remote_root):
    from debugpilot.debugger import GoAttachSession

    invalid = CodeProject('invalid', tmp_path, (), None,
                          GoAttach('127.0.0.1', peer.port, remote_root))
    session = GoAttachSession()
    with pytest.raises(DebugError, match='Invalid goAttach'):
        await session.start(invalid, {})
    await session.close()

    assert peer.connections == 0
    assert list(tmp_path.iterdir()) == []


async def test_startup_cancel_does_not_issue_target_termination(tmp_path):
    from debugpilot.debugger import GoAttachSession

    attach_received = asyncio.Event()
    writer_closed = asyncio.Event()
    commands = []

    async def hold_attach(reader, writer):
        try:
            while True:
                header = await reader.readuntil(b'\r\n\r\n')
                length = int(header.split(b':', 1)[1].strip())
                request = json.loads(await reader.readexactly(length))
                command = request['command']
                commands.append(request)
                if command == 'initialize':
                    await DAPPeer._send(writer, {
                        'type': 'response', 'request_seq': request['seq'],
                        'command': command, 'success': True, 'body': {},
                    })
                elif command == 'attach':
                    attach_received.set()
                    await DAPPeer._send(writer, {
                        'type': 'event', 'event': 'initialized', 'body': {},
                    })
                elif command == 'configurationDone':
                    await DAPPeer._send(writer, {
                        'type': 'response', 'request_seq': request['seq'],
                        'command': command, 'success': True, 'body': {},
                    })
                elif command == 'disconnect':
                    await DAPPeer._send(writer, {
                        'type': 'response', 'request_seq': request['seq'],
                        'command': command, 'success': True, 'body': {},
                    })
                    break
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            writer_closed.set()

    server = await asyncio.start_server(hold_attach, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    session = None
    try:
        from debugpilot.debugger import GoAttachSession

        session = GoAttachSession(timeout=2)
        task = asyncio.create_task(session.start(profile(tmp_path, port), {}))
        async with asyncio.timeout(2):
            await attach_received.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(2):
            await writer_closed.wait()
        assert session.state == 'closed'
        disconnect = next(item for item in commands if item['command'] == 'disconnect')
        assert disconnect['arguments'] == {'terminateDebuggee': False}
        assert not any(item['command'] == 'terminate' for item in commands)
    finally:
        if session is not None:
            await session.close()
        server.close()
        await server.wait_closed()


@pytest.mark.skipif(os.name == 'nt', reason='the remote root must be a POSIX path')
async def test_real_headless_delve_breakpoint_disconnect_and_reconnect(tmp_path):
    from debugpilot.debugger import GoAttachSession

    repository = Path(__file__).parents[2]
    dlv = shutil.which('dlv') or str(repository / '.tools' / 'bin' / 'dlv')
    if not await asyncio.to_thread(Path(dlv).is_file):
        pytest.skip('Delve is not installed in the repository environment.')
    remote_root = tmp_path / 'remote'
    workspace = tmp_path / 'workspace'
    remote_root.mkdir()
    workspace.mkdir()
    source = workspace / 'main.go'
    remote_source = remote_root / 'main.go'
    marker = remote_root / 'ticks'
    source_text = (
        'package main\nimport ("fmt"; "os"; "strconv"; "time")\n'
        'func main() {\n answer := 41\n fmt.Print(answer)\n'
        ' for i := 0; ; i++ { os.WriteFile("ticks", []byte(strconv.Itoa(i)), 0600); '
        'time.Sleep(30*time.Millisecond) }\n}\n')
    source.write_text(source_text, encoding='utf-8')
    remote_source.write_text(source_text, encoding='utf-8')
    (remote_root / 'go.mod').write_text(
        'module example.invalid/attach\n\ngo 1.22\n', encoding='utf-8')
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
        dlv, 'debug', '--headless', '--accept-multiclient', '--api-version=2',
        '--log', '--log-output=dap', '--listen', f'127.0.0.1:{port}', '.', cwd=remote_root,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, 'GOTOOLCHAIN': 'local', 'GOWORK': 'off'},
    )
    stdout, stderr = [], []
    listening = asyncio.Event()

    async def capture(stream, lines):
        while line := await stream.readline():
            text = line.decode('utf-8', errors='replace').rstrip()
            lines.append(text)
            if 'API server listening at:' in text:
                listening.set()

    readers = [asyncio.create_task(capture(process.stdout, stdout)),
               asyncio.create_task(capture(process.stderr, stderr))]
    events = []
    outputs = []
    session = GoAttachSession(timeout=10, on_event=events.append,
                              on_output=lambda category, text: outputs.append((category, text)))
    target = CodeProject('Owned Delve fixture', workspace, (), None,
                         GoAttach('127.0.0.1', port, remote_root.as_posix()))
    try:
        try:
            async with asyncio.timeout(12):
                await listening.wait()
            await session.start(target, {source: [5]})
        except Exception as error:
            pytest.fail(
                f'Owned Delve attach failed: {error!r}; returncode={process.returncode}; '
                f'events={events!r}; output={outputs!r}; stdout={stdout!r}; stderr={stderr!r}')
        try:
            async with asyncio.timeout(5):
                while session.state != 'stopped':
                    await session.events.get()
        except TimeoutError:
            pytest.fail(
                f'No stopped event; returncode={process.returncode}; events={events!r}; '
                f'output={outputs!r}; stdout={stdout!r}; stderr={stderr!r}')
        verified = session.verified_breakpoints[str(source.resolve())]
        assert verified and verified[0]['verified'] is True
        frames = await session.stack()
        assert frames[0]['source']['path'] == str(source.resolve())
        scopes = await session.scopes(frames[0]['id'])
        variables = [value for scope in scopes if not scope.get('expensive')
                     for value in await session.variables(scope['variablesReference'])]
        assert any(value['name'] == 'answer' and value['value'] == '41' for value in variables)
        await session.continue_execution()
        await session.close()
        first_close = next(item for item in reversed(events)
                           if item.get('event') == 'transportClosed')
        first_disconnect_reason = first_close['body']['message']
        assert isinstance(first_disconnect_reason, str)
        initial = marker.read_text(encoding='utf-8')
        await asyncio.sleep(0.15)
        assert marker.read_text(encoding='utf-8') != initial
        await session.start(target, {})
        await session.close()
        close_event = next(item for item in reversed(events)
                           if item.get('event') == 'transportClosed')
        disconnect_reason = close_event['body']['message']
        assert isinstance(disconnect_reason, str)
        assert process.returncode is None, (
            f'returncode={process.returncode}; disconnect={disconnect_reason!r}; '
            f'stdout={stdout!r}; stderr={stderr!r}')
    finally:
        await session.close()
        if process.returncode is None:
            process.terminate()
        await asyncio.wait_for(process.wait(), 5)
        for task in readers:
            task.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
