"""Node public contract: real Inspector, not a simulated adapter."""
import asyncio
import json

import pytest

from debugpilot.debugger import DebugError, NodeDebugSession
from debugpilot.storage.code_projects import CodeProject


async def event(session, name):
    async with asyncio.timeout(20):
        while True:
            message = await session.events.get()
            if message.get('event') == name:
                return message.get('body', {})


async def test_real_node_breakpoint_stack_locals_steps_and_exit(tmp_path):
    source = tmp_path / 'server.js'
    source.write_text('function calculate(value) {\n  const result = value + 1;\n'
                      '  return result;\n}\nlet answer = 41;\n'
                      'answer = calculate(answer);\nconsole.log(`RESULT:${answer}`);\n')
    output = []
    profile = CodeProject('node', tmp_path, ('node', 'server.js'))
    session = NodeDebugSession(on_output=lambda category, text: output.append((category, text)))
    try:
        await session.start(profile, {source: [6]})
        await event(session, 'stopped')
        frames = await session.stack()
        assert frames[0]['source']['path'] == str(source)
        assert frames[0]['line'] == 6
        scopes = await session.scopes(frames[0]['id'])
        values = [v for scope in scopes if not scope['expensive']
                  for v in await session.variables(scope['variablesReference'])]
        assert any(v['name'] == 'answer' and v['value'] == '41' for v in values)
        assert session.verified_breakpoints[str(source)][0]['verified']
        await session.step_in()
        await event(session, 'stopped')
        assert (await session.stack())[0]['name'] == 'calculate'
        await session.step_over()
        await event(session, 'stopped')
        await session.step_out()
        await event(session, 'stopped')
        await session.set_breakpoints(source, [])
        await session.continue_execution()
        assert (await event(session, 'exited'))['exitCode'] == 0
        await event(session, 'terminated')
        assert ''.join(t for c, t in output if c == 'stdout') == 'RESULT:42\n'
        assert ''.join(t for c, t in output if c == 'stderr') == ''
        assert profile.command == ('node', 'server.js')
    finally:
        await session.close()
        await session.close()
    assert session.state == 'closed'
    assert session.thread_id is None
    assert session.verified_breakpoints == {}


@pytest.mark.parametrize('command', [('node',), ('node', '-e', 'console.log(1)'),
    ('node', '--watch', 'server.js'), ('npm', 'run', 'dev'), ('go', 'run', 'main.go')])
async def test_rejected_launch_never_runs_or_mutates(tmp_path, command):
    profile = CodeProject('bad', tmp_path, command)
    output = []
    session = NodeDebugSession(on_output=lambda *args: output.append(args))
    with pytest.raises(DebugError, match='Supported Node commands'):
        await session.start(profile, {})
    assert profile.command == command
    assert session.state == 'idle'
    assert session.profile is None
    assert session.requested_breakpoints == {}
    assert output == []
    assert list(tmp_path.iterdir()) == []
    await session.close()


async def test_missing_runtime_and_invalid_breakpoint_do_not_launch(tmp_path):
    profile = CodeProject('missing', tmp_path, (str(tmp_path / 'node'), 'server.js'))
    session = NodeDebugSession()
    with pytest.raises(DebugError, match='Executable not found'):
        await session.start(profile, {})
    assert session.state == 'idle'
    assert session.profile is None
    with pytest.raises(DebugError, match='positive 1-based'):
        await session.start(
            CodeProject('node', tmp_path, ('node', 'server.js')), {'server.js': [0]})
    assert session.state == 'idle'
    assert session.requested_breakpoints == {}
    assert list(tmp_path.iterdir()) == []
    await session.close()


async def test_stop_and_startup_cancellation_are_owned(tmp_path):
    source = tmp_path / 'server.js'
    source.write_text('let answer = 41;\nsetInterval(() => {}, 1000);\n')
    profile = CodeProject('stop', tmp_path, ('node', 'server.js'))
    session = NodeDebugSession()
    try:
        await session.start(profile, {source: [2]})
        await event(session, 'stopped')
        await asyncio.gather(session.close(), session.close())
        assert session.state == 'closed'
        assert session.thread_id is None
    finally:
        await session.close()
    started = asyncio.Event()
    session = NodeDebugSession(on_event=lambda m: (
        started.set() if m.get('event') == 'adapterStarted' else None))
    task = asyncio.create_task(session.start(profile, {}))
    await asyncio.wait_for(started.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await session.close()
    assert session.state == 'closed'
    assert session.verified_breakpoints == {}


@pytest.mark.parametrize('exit_code', [0, 23])
async def test_unterminated_output_and_real_exit_status(tmp_path, exit_code):
    source = tmp_path / 'server.js'
    source.write_text('process.stdout.write("OUT");\nprocess.stderr.write("ERR");\n'
                      f'process.exitCode = {exit_code};\n')
    output = []
    session = NodeDebugSession(timeout=5, on_output=lambda c, t: output.append((c, t)))
    try:
        await session.start(CodeProject('tail', tmp_path, ('node', 'server.js')), {})
        assert (await event(session, 'exited'))['exitCode'] == exit_code
        await event(session, 'terminated')
        # CodeSession is a PTY: stdout/stderr are intentionally merged in order.
        assert ''.join(t for c, t in output) == 'OUTERR'
    finally:
        await session.close()


async def test_stop_removes_owned_node_descendant(tmp_path):
    import socket

    child = ('require("net").createServer().listen(0, "127.0.0.1", function() {'
             'console.log("CHILD:" + this.address().port); });')
    source = tmp_path / 'server.js'
    source.write_text('require("child_process").spawn(process.execPath, '
                      f'["-e", {json.dumps(child)}], {{stdio: "inherit"}});\n'
                      'setInterval(() => {}, 1000);\n')
    ready = asyncio.Event()
    output = []
    def receive(category, text):
        output.append(text)
        if 'CHILD:' in ''.join(output):
            ready.set()
    session = NodeDebugSession(on_output=receive)
    try:
        await session.start(CodeProject('child', tmp_path, ('node', 'server.js')), {})
        await asyncio.wait_for(ready.wait(), 15)
        port = int(''.join(output).split('CHILD:', 1)[1].strip())
        with socket.create_connection(('127.0.0.1', port), timeout=2):
            pass
        await session.close()
        # Job Object teardown propagates asynchronously to Windows descendants.
        async with asyncio.timeout(3):
            while True:
                try:
                    reader, writer = await asyncio.open_connection('127.0.0.1', port)
                except OSError:
                    break
                writer.close()
                await writer.wait_closed()
                await asyncio.sleep(0.02)
        assert session.state == 'closed'
    finally:
        await session.close()


async def test_explicit_npm_target_is_not_npm_cli(tmp_path):
    source = tmp_path / 'server.js'
    source.write_text('console.log("TARGET:" + process.argv[2]);\n')
    profile = CodeProject('npm', tmp_path, ('npm', 'run', 'dev'),
                          node_debug=('node', 'server.js', 'literal ; &'))
    output = []
    session = NodeDebugSession(on_output=lambda c, t: output.append(t))
    try:
        await session.start(profile, {})
        assert (await event(session, 'exited'))['exitCode'] == 0
        await event(session, 'terminated')
        assert ''.join(output) == 'TARGET:literal ; &\n'
        assert session.profile == profile
        assert profile.command == ('npm', 'run', 'dev')
    finally:
        await session.close()
