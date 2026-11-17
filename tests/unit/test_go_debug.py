"""Required real Go/Delve evidence through the public session API; no tool skips."""

import asyncio
import os
import shutil
import socket
import sys
from pathlib import Path

import pytest

from debugpilot.debugger import DebugError, GoDebugSession
from debugpilot.debugger.go import DAPClient
from debugpilot.storage.code_projects import CodeProject


async def event(session, name):
    async with asyncio.timeout(120):
        while True:
            message = await session.events.get()
            if message.get('event') == name:
                return message.get('body', {})


def project(tmp_path, target='main.go', args=()):
    (tmp_path / 'go.mod').write_text('module example.invalid/debugpilot\n\ngo 1.22\n')
    return CodeProject('Go sample', tmp_path, ('go', 'run', target, *args))


@pytest.mark.parametrize('target', ['main.go', '.'])
async def test_real_breakpoint_stack_locals_steps_and_exit(tmp_path, target, monkeypatch):
    source = tmp_path / 'main.go'
    source.write_text(
        'package main\nimport "fmt"\n'
        'func calculate(value int) int {\n result := value + 1\n return result\n}\n'
        'func main() {\n answer := 41\n answer = calculate(answer)\n'
        ' fmt.Printf("RESULT:%d\\n", answer)\n}\n'
    )
    # A broken Git marker makes Go's automatic VCS metadata probe fail unless the
    # debug-only launch explicitly opts out of build metadata.
    (tmp_path / '.git').mkdir()
    (tmp_path / '.git' / 'HEAD').write_text('not a valid Git ref\n')
    profile = project(tmp_path, target)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    output = []
    launch_requests = []
    request = DAPClient.request

    async def capture_request(client, command, arguments=None, **options):
        if command == 'launch':
            launch_requests.append(arguments.copy())
        return await request(client, command, arguments, **options)

    monkeypatch.setattr(
        'debugpilot.debugger.go.DAPClient.request', capture_request)
    session = GoDebugSession(on_output=lambda c, t: output.append((c, t)))
    try:
        await session.start(profile, {source: [9, 9]})
        await event(session, 'stopped')
        assert session.state == 'stopped'
        assert session.profile == profile
        assert profile.command == ('go', 'run', target)
        assert len(launch_requests) == 1
        assert launch_requests[0]['buildFlags'] == '-buildvcs=false'
        assert Path(launch_requests[0]['output']).name == 'debugpilot-target'
        assert launch_requests[0]['outputMode'] == 'remote'
        assert 'env' not in launch_requests[0]
        assert session.requested_breakpoints == {str(source): (9,)}
        assert session.verified_breakpoints[str(source)][0]['verified'] is True
        frames = await session.stack()
        assert frames[0]['line'] == 9
        assert frames[0]['source']['path'] == str(source)
        scopes = await session.scopes(frames[0]['id'])
        values = [v for s in scopes if not s['expensive']
                  for v in await session.variables(s['variablesReference'])]
        assert any(v['name'] == 'answer' and v['value'] == '41' for v in values)
        await session.step_in()
        await event(session, 'stopped')
        assert (await session.stack())[0]['name'].endswith('calculate')
        await session.step_over()
        await event(session, 'stopped')
        await session.step_out()
        await event(session, 'stopped')
        await session.set_breakpoints(source, [])
        assert session.requested_breakpoints[str(source)] == ()
        await session.continue_execution()
        await event(session, 'terminated')
        assert ''.join(t for c, t in output if c == 'stdout') == 'RESULT:42\n'
        assert ''.join(t for c, t in output if c == 'stderr') == ''
        assert session.exit_code in (None, 0)
        async with asyncio.timeout(5):
            while session.state != 'closed':  # noqa: ASYNC110
                await asyncio.sleep(0.02)
    finally:
        await asyncio.gather(session.close(), session.close())
        await session.close()
    assert session.thread_id is None
    assert session.verified_breakpoints == {}
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert after == before


@pytest.mark.parametrize('command', [
    ('go',), ('go', 'run'), ('go', 'test'), ('go', 'run', '-race', '.'),
    ('go', 'run', './...'), ('go', 'run', './main.go'), ('go', 'run', 'other.go'),
    ('go', 'run', 'main.go', 'other.go'), ('dlv', 'exec', 'binary'),
    ('go', 'run', '-exec', 'echo', 'main.go'),
])
async def test_unsupported_grammar_never_runs_or_mutates(tmp_path, command):
    output = []
    profile = CodeProject('unsupported', tmp_path, command)
    session = GoDebugSession(on_output=lambda *args: output.append(args))
    with pytest.raises(DebugError, match='Supported Go commands:'):
        await session.start(profile, {})
    assert session.state == 'idle'
    assert session.profile is None
    assert session.requested_breakpoints == {}
    assert session.verified_breakpoints == {}
    assert session.exit_code is None
    assert profile.command == command
    assert output == []
    assert list(tmp_path.iterdir()) == []
    await session.close()


async def test_missing_dlv_does_not_run_target(tmp_path, monkeypatch):
    profile = project(tmp_path)
    source = tmp_path / 'main.go'
    source.write_text('package main\nimport "os"\nfunc main(){os.WriteFile("ran",nil,0600)}\n')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    which = shutil.which
    monkeypatch.setattr(shutil, 'which', lambda name: None if name == 'dlv' else which(name))
    output = []
    session = GoDebugSession(on_output=lambda *args: output.append(args))
    with pytest.raises(DebugError, match='Delve.*dlv.*PATH.*No run-mode fallback'):
        await session.start(profile, {})
    assert session.state == 'idle'
    assert session.profile is None
    assert session.requested_breakpoints == {}
    assert output == []
    assert profile.command == ('go', 'run', 'main.go')
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    await session.close()


async def test_invalid_breakpoint_does_not_launch(tmp_path):
    profile = project(tmp_path)
    session = GoDebugSession()
    with pytest.raises(DebugError, match='positive 1-based'):
        await session.start(profile, {'main.go': [0]})
    assert session.state == 'idle'
    assert session.profile is None
    assert session.requested_breakpoints == {}
    await session.close()


async def test_startup_cancellation_and_concurrent_close(tmp_path):
    profile = project(tmp_path)
    (tmp_path / 'main.go').write_text('package main\nfunc main(){}\n')
    started = asyncio.Event()
    session = GoDebugSession(on_event=lambda m: (
        started.set() if m.get('event') == 'adapterStarted' else None))
    task = asyncio.create_task(session.start(profile, {}))
    await asyncio.wait_for(started.wait(), 15)
    await asyncio.gather(session.close(), session.close())
    with pytest.raises(asyncio.CancelledError):
        await task
    await session.close()
    assert session.state == 'closed'
    assert session.thread_id is None
    assert session.verified_breakpoints == {}
    assert sorted(p.name for p in tmp_path.iterdir()) == ['go.mod', 'main.go']


@pytest.mark.parametrize('exit_code', [0, 23])
async def test_exact_output_args_and_target_exit(tmp_path, exit_code):
    profile = project(tmp_path, args=('literal ; &',))
    (tmp_path / 'main.go').write_text(
        'package main\nimport ("fmt"; "os")\nfunc main(){\n'
        'fmt.Print(os.Args[1]); fmt.Fprint(os.Stderr,"ERR");'
        f'os.Exit({exit_code})\n}}\n'
    )
    output = []
    session = GoDebugSession(on_output=lambda c, t: output.append((c, t)))
    try:
        await session.start(profile, {})
        await event(session, 'terminated')
        assert ''.join(t for c, t in output if c == 'stdout') == 'literal ; &'
        assert ''.join(t for c, t in output if c == 'stderr') == 'ERR'
        assert session.exit_code in (None, exit_code)
    finally:
        await session.close()


@pytest.mark.parametrize('exit_code', [0, 23])
async def test_dap_exit_event_preserves_authoritative_status(exit_code):
    session = GoDebugSession()
    assert session.exit_code is None
    session._event({'event': 'exited', 'body': {'exitCode': exit_code}})
    assert session.exit_code == exit_code
    await session.close()


async def test_terminated_without_exit_event_keeps_status_unknown():
    session = GoDebugSession()
    session._event({'event': 'terminated', 'body': {}})
    await session.close()
    assert session.exit_code is None


async def test_stop_removes_owned_descendant(tmp_path):
    profile = project(tmp_path)
    (tmp_path / 'main.go').write_text(
        'package main\nimport ("fmt"; "net"; "os"; "os/exec"; "time")\n'
        'func main(){\nif len(os.Args)>1 {\n'
        'l,e:=net.Listen("tcp","127.0.0.1:0"); if e!=nil {panic(e)}\n'
        'fmt.Println("CHILD:"+l.Addr().String()); time.Sleep(60*time.Second); return\n}\n'
        'exe,_:=os.Executable(); c:=exec.Command(exe,"child");'
        'c.Stdout=os.Stdout; c.Stderr=os.Stderr; if e:=c.Start();e!=nil{panic(e)}\n'
        'time.Sleep(60*time.Second)\n}\n'
    )
    output, ready = [], asyncio.Event()

    def receive(category, text):
        output.append(text)
        if 'CHILD:' in ''.join(output) and '\n' in ''.join(output):
            ready.set()

    session = GoDebugSession(on_output=receive)
    try:
        await session.start(profile, {})
        await asyncio.wait_for(ready.wait(), 30)
        port = int(''.join(output).split('CHILD:127.0.0.1:', 1)[1].strip())
        with socket.create_connection(('127.0.0.1', port), timeout=2):
            pass
        await asyncio.gather(session.close(), session.close())
        async with asyncio.timeout(5):
            while True:
                try:
                    _, writer = await asyncio.open_connection('127.0.0.1', port)
                except OSError:
                    break
                writer.close()
                await writer.wait_closed()
                await asyncio.sleep(0.02)
        assert session.state == 'closed'
    finally:
        await session.close()


def slow_go(tmp_path, monkeypatch, seconds):
    """Put a `go` on PATH whose builds take `seconds` longer; it records each build PID."""
    real_go = shutil.which('go')
    tools = tmp_path.parent / f'{tmp_path.name}-slow-go'
    tools.mkdir()
    builds = tools / 'builds'
    wrapper = tools / 'go'
    wrapper.write_text(
        '#!/bin/sh\n'
        f'if [ "$1" = build ]; then echo $$ >> "{builds}"; sleep {seconds}; fi\n'
        f'exec "{real_go}" "$@"\n')
    wrapper.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tools}{os.pathsep}{os.environ["PATH"]}')
    return builds


def running(pid):
    status = Path(f'/proc/{pid}/status')
    return status.exists() and 'zombie' not in status.read_text(errors='replace').lower()


def collect_states(states):
    return lambda message: (
        states.append(message['body']['state']) if message.get('event') == 'state' else None)


@pytest.mark.skipif(os.name == 'nt', reason='the slow go wrapper is a POSIX shell script')
async def test_build_longer_than_startup_timeout_is_not_an_error(tmp_path, monkeypatch):
    profile = project(tmp_path)
    (tmp_path / 'main.go').write_text('package main\nfunc main(){}\n')
    slow_go(tmp_path, monkeypatch, 4)
    states = []
    session = GoDebugSession(on_event=collect_states(states), timeout=2)
    try:
        await asyncio.wait_for(session.start(profile, {}), 60)
        assert states[:2] == ['starting', 'building']
        assert 'running' in states or 'closed' in states
    finally:
        await session.close()


async def test_build_error_is_reported_without_waiting_for_a_timeout(tmp_path):
    profile = project(tmp_path)
    (tmp_path / 'main.go').write_text('package main\nfunc main(){ undefinedCall() }\n')
    output = []
    session = GoDebugSession(on_output=lambda category, text: output.append(text), timeout=60)
    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(DebugError, match='^Unable to build the Go program: .*Build error'):
        await asyncio.wait_for(session.start(profile, {}), 120)
    # Generous for a cold build, still well below the 60 s startup timeout.
    assert loop.time() - started < 45
    # Delve sends the compiler message to the debug output, which the UI shows.
    assert 'undefinedCall' in ''.join(output)
    assert session.state == 'closed'
    await session.close()


@pytest.mark.skipif(os.name == 'nt', reason='the slow go wrapper is a POSIX shell script')
async def test_stop_during_build_cancels_start_and_ends_the_build(tmp_path, monkeypatch):
    profile = project(tmp_path)
    (tmp_path / 'main.go').write_text('package main\nfunc main(){}\n')
    builds = slow_go(tmp_path, monkeypatch, 30)
    states = []
    session = GoDebugSession(on_event=collect_states(states), timeout=2)
    task = asyncio.create_task(session.start(profile, {}))
    async with asyncio.timeout(30):
        while not builds.exists() or 'building' not in states:  # noqa: ASYNC110
            await asyncio.sleep(0.05)
    await session.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.state == 'closed'
    pid = int(builds.read_text().split()[0])
    async with asyncio.timeout(5):
        while running(pid):  # noqa: ASYNC110 — poll the observable build process
            await asyncio.sleep(0.05)


@pytest.mark.skipif(os.name == 'nt', reason='the fake dlv is a POSIX script')
async def test_delve_crash_during_build_keeps_the_startup_error(tmp_path, monkeypatch):
    profile = project(tmp_path)
    (tmp_path / 'main.go').write_text('package main\nfunc main(){}\n')
    tools = tmp_path.parent / f'{tmp_path.name}-fake-dlv'
    tools.mkdir()
    fake = tools / 'dlv'
    # Answers initialize like Delve, then prints a fatal error and dies on launch.
    fake.write_text(f'''#!{sys.executable}
import json, os, socket, sys
port = int(sys.argv[sys.argv.index('--listen') + 1].rsplit(':', 1)[1])
server = socket.create_server(('127.0.0.1', port))
connection, _ = server.accept()
stream = connection.makefile('rb')
while True:
    header = b''
    while not header.endswith(b'\\r\\n\\r\\n'):
        header += stream.read(1)
    request = json.loads(stream.read(int(header.split(b':')[1])))
    if request['command'] == 'launch':
        print('fatal: delve crashed while building', file=sys.stderr, flush=True)
        os._exit(3)
    data = json.dumps({{'type': 'response', 'seq': 1, 'request_seq': request['seq'],
                        'command': request['command'], 'success': True, 'body': {{}}}}).encode()
    connection.sendall(b'Content-Length: %d\\r\\n\\r\\n' % len(data) + data)
''')
    fake.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tools}{os.pathsep}{os.environ["PATH"]}')
    session = GoDebugSession(timeout=30)
    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(DebugError) as raised:
        await asyncio.wait_for(session.start(profile, {}), 60)
    message = str(raised.value)
    assert message.startswith(f'Unable to start Go debugging with Delve at {fake}.')
    assert 'No run-mode fallback.' in message
    # The reason replaces the old generic 'startup timed out' after the full timeout.
    assert 'Debug adapter disconnected' in message
    assert loop.time() - started < 10
    assert session.state == 'closed'
    await session.close()


def test_delve_build_notice_is_console_output_not_the_programs():
    # Delve 1.27+ sends "Building <program>" as stdout while it compiles.
    output = []
    session = GoDebugSession(on_output=lambda category, text: output.append((category, text)))
    session.state = 'building'
    session._event({'event': 'output', 'body': {'category': 'stdout',
                                                'output': 'Building /work/main.go\n'}})
    session.state = 'running'
    # Once running, a program printing the same words is its own output.
    session._event({'event': 'output', 'body': {'category': 'stdout',
                                                'output': 'Building houses\n'}})
    assert output == [('console', 'Building /work/main.go\n'), ('stdout', 'Building houses\n')]


async def test_build_folder_cleanup_waits_for_windows_to_release_the_program(monkeypatch):
    # Windows keeps the built .exe locked a moment after Delve and the program exit.
    from debugpilot.debugger import go

    attempts = []

    def locked_twice(build):
        attempts.append(build)
        return len(attempts) > 2

    monkeypatch.setattr(go, '_remove_build_dir', locked_twice)
    monkeypatch.setattr(go, 'BUILD_CLEANUP_DELAY', 0)
    session = GoDebugSession()
    session._build_dir = object()
    await session._cleanup()
    assert len(attempts) == 3 and session._build_dir is None


async def test_build_folder_left_locked_never_fails_the_close(monkeypatch):
    from debugpilot.debugger import go

    monkeypatch.setattr(go, '_remove_build_dir', lambda build: False)
    monkeypatch.setattr(go, 'BUILD_CLEANUP_DELAY', 0)
    session = GoDebugSession()
    session._build_dir = object()
    await session._cleanup()  # Left to the temporary folder; no exception.
    assert session._build_dir is None


async def test_windows_stack_paths_from_delve_use_the_native_form(monkeypatch):
    from debugpilot.debugger import go

    async def frames(self):
        return [{'source': {'path': 'C:/work/app/main.go'}}, {'source': {}}]

    monkeypatch.setattr(go.PythonDebugSession, 'stack', frames)
    monkeypatch.setattr(go.os, 'name', 'nt')
    stack = await GoDebugSession().stack()
    assert stack[0]['source']['path'] == 'C:\\work\\app\\main.go'
    assert stack[1]['source'] == {}


def test_a_cleanup_that_raises_counts_as_still_locked(tmp_path):
    # Some Python 3.12 releases let PermissionError out of TemporaryDirectory.cleanup.
    from debugpilot.debugger import go

    class Locked:
        name = str(tmp_path)

        def cleanup(self):
            raise PermissionError(5, 'Access is denied')

    assert go._remove_build_dir(Locked()) is False
