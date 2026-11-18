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


async def test_real_node_typescript_breakpoint_lines_stack_and_locals(tmp_path):
    # Node's type stripping keeps positions, so .ts lines are the debugged lines.
    source = tmp_path / 'main.ts'
    source.write_text('interface Order {\n  id: number;\n  total: number;\n}\n'
                      'type Money = number;\n'
                      'function tax(order: Order, rate: Money): Money {\n'
                      '  const amount: Money = order.total * rate;\n'
                      '  return amount;\n}\n'
                      'const order: Order = { id: 7, total: 100 };\n'
                      'console.log(`TAX:${tax(order, 0.25)}`);\n')
    output = []
    profile = CodeProject('ts', tmp_path, ('node', 'main.ts'))
    session = NodeDebugSession(on_output=lambda category, text: output.append((category, text)))
    try:
        await session.start(profile, {source: [8]})
        await event(session, 'stopped')
        frames = await session.stack()
        assert frames[0]['source']['path'] == str(source)
        assert (frames[0]['name'], frames[0]['line']) == ('tax', 8)
        scopes = await session.scopes(frames[0]['id'])
        values = {v['name']: v['value'] for scope in scopes if not scope['expensive']
                  for v in await session.variables(scope['variablesReference'])}
        assert values['amount'] == '25' and values['rate'] == '0.25'
        assert session.verified_breakpoints[str(source)][0] == {
            'id': session.verified_breakpoints[str(source)][0]['id'], 'verified': True,
            'line': 8}
        await session.continue_execution()
        assert (await event(session, 'exited'))['exitCode'] == 0
        assert ''.join(t for c, t in output if c == 'stdout') == 'TAX:25\n'
    finally:
        await session.close()


@pytest.mark.parametrize('script', ['main.ts', 'main.mts', 'main.cts', 'MAIN.TS', 'server.js'])
def test_typescript_and_javascript_targets_are_valid(script):
    from debugpilot.storage.code_projects import valid_node_target

    assert valid_node_target(('node', script, '--port', '3000'))


@pytest.mark.parametrize('script', ['main.tsx', 'main.d.ts.map', 'main.py', 'main'])
def test_other_targets_stay_invalid(script):
    from debugpilot.storage.code_projects import valid_node_target

    assert not valid_node_target(('node', script))


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
    session = NodeDebugSession(timeout=60, on_output=lambda c, t: output.append((c, t)))
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


def test_windows_breakpoints_match_typescript_named_by_path(monkeypatch):
    # Node on Windows names .ts scripts by their path, and .js scripts by file:// URL.
    import nturl2path
    import re

    from debugpilot.debugger import node

    monkeypatch.setattr(node.os, 'name', 'nt')
    # Windows' own file:// conversion, whatever system runs the test.
    monkeypatch.setattr(node, 'url2pathname', nturl2path.url2pathname)
    url = 'file:///C:/work/app/main.ts'
    fields = NodeDebugSession()._breakpoint_url(url)
    pattern = re.compile(fields['urlRegex'])
    assert pattern.match(url) and pattern.match('C:\\work\\app\\main.ts')
    assert not pattern.match('C:\\work\\app\\main.tsx')
    assert node._source('C:\\work\\app\\main.ts') is not None


def test_other_systems_keep_the_exact_breakpoint_url(monkeypatch):
    from debugpilot.debugger import node

    monkeypatch.setattr(node.os, 'name', 'posix')
    assert NodeDebugSession()._breakpoint_url('file:///work/main.ts') == {
        'url': 'file:///work/main.ts'}
