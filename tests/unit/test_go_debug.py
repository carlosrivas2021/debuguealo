"""Required real Go/Delve evidence through the public session API; no tool skips."""

import asyncio
import shutil
import socket

import pytest

from debugpilot.debugger import DebugError, GoDebugSession
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
async def test_real_breakpoint_stack_locals_steps_and_exit(tmp_path, target):
    source = tmp_path / 'main.go'
    source.write_text(
        'package main\nimport "fmt"\n'
        'func calculate(value int) int {\n result := value + 1\n return result\n}\n'
        'func main() {\n answer := 41\n answer = calculate(answer)\n'
        ' fmt.Printf("RESULT:%d\\n", answer)\n}\n'
    )
    profile = project(tmp_path, target)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    output = []
    session = GoDebugSession(on_output=lambda c, t: output.append((c, t)))
    try:
        await session.start(profile, {source: [9, 9]})
        await event(session, 'stopped')
        assert session.state == 'stopped'
        assert session.profile == profile
        assert profile.command == ('go', 'run', target)
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
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


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
