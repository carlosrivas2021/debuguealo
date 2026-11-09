"""Conditional breakpoints and logpoints through each real debug adapter."""

import asyncio

import pytest

from debugpilot.debugger import GoDebugSession, NodeDebugSession, PythonDebugSession
from debugpilot.storage.breakpoints import BreakpointOptions
from debugpilot.storage.code_projects import CodeProject

# Each program sums 0..4; the loop body is on LOOP_LINE and prints TOTAL:10 at the end.
PROGRAMS = {
    'python': ('main.py', ('python3', '-u', 'main.py'), 3,
               'total = 0\nfor i in range(5):\n    total += i\n'
               'print(f"TOTAL:{total}", flush=True)\n'),
    'go': ('main.go', ('go', 'run', 'main.go'), 8,
           'package main\n\nimport "fmt"\n\nfunc main() {\n\ttotal := 0\n'
           '\tfor i := 0; i < 5; i++ {\n\t\ttotal += i\n\t}\n'
           '\tfmt.Printf("TOTAL:%d\\n", total)\n}\n'),
    'node': ('main.js', ('node', 'main.js'), 3,
             'let total = 0;\nfor (let i = 0; i < 5; i++) {\n  total += i;\n}\n'
             'console.log(`TOTAL:${total}`);\n'),
}
SESSIONS = {'python': PythonDebugSession, 'go': GoDebugSession, 'node': NodeDebugSession}
CONDITIONS = {'python': 'i == 3', 'go': 'i == 3', 'node': 'i === 3'}


async def next_event(session, *names):
    async with asyncio.timeout(120):
        while True:
            message = await session.events.get()
            if message.get('event') in names:
                return message.get('event'), message.get('body', {})


def program(tmp_path, language):
    name, command, line, text = PROGRAMS[language]
    source = tmp_path / name
    source.write_text(text)
    if language == 'go':
        (tmp_path / 'go.mod').write_text('module example.invalid/options\n\ngo 1.22\n')
    return CodeProject(language, tmp_path, command), source, line


async def local_value(session, name):
    frame = (await session.stack())[0]
    for scope in await session.scopes(frame['id']):
        if scope.get('expensive'):
            continue
        for variable in await session.variables(scope['variablesReference']):
            if variable['name'] == name:
                return frame['line'], variable['value']
    raise AssertionError(f'{name} not found')


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_conditional_breakpoint_stops_only_when_the_condition_holds(tmp_path, language):
    profile, source, line = program(tmp_path, language)
    output = []
    session = SESSIONS[language](on_output=lambda category, text: output.append(text))
    try:
        await session.start(profile, {str(source): (line,)}, {
            str(source): {line: BreakpointOptions(condition=CONDITIONS[language])}})
        name, _ = await next_event(session, 'stopped', 'terminated')
        assert name == 'stopped'
        assert await local_value(session, 'i') == (line, '3')
        await session.continue_execution()
        # The condition fails for i == 4, so the next event is the end of the program.
        name, _ = await next_event(session, 'stopped', 'terminated')
        assert name == 'terminated'
        assert 'TOTAL:10' in ''.join(output)
    finally:
        await session.close()


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_logpoint_writes_output_without_stopping(tmp_path, language):
    profile, source, line = program(tmp_path, language)
    output = []
    session = SESSIONS[language](on_output=lambda category, text: output.append(text))
    try:
        await session.start(profile, {str(source): (line,)}, {
            str(source): {line: BreakpointOptions(log_message='iteration {i}')}})
        name, _ = await next_event(session, 'stopped', 'terminated')
        assert name == 'terminated'
        text = ''.join(output)
        for value in range(5):
            assert f'iteration {value}' in text
        assert 'TOTAL:10' in text
    finally:
        await session.close()


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_options_change_while_running_through_set_breakpoints(tmp_path, language):
    profile, source, line = program(tmp_path, language)
    session = SESSIONS[language]()
    try:
        await session.start(profile, {str(source): (line,)})
        name, _ = await next_event(session, 'stopped', 'terminated')
        assert name == 'stopped'
        assert await local_value(session, 'i') == (line, '0')
        await session.set_breakpoints(
            str(source), (line,), {line: BreakpointOptions(condition=CONDITIONS[language])})
        await session.continue_execution()
        name, _ = await next_event(session, 'stopped', 'terminated')
        assert name == 'stopped'
        assert await local_value(session, 'i') == (line, '3')
    finally:
        await session.close()


class RecordingClient:
    def __init__(self):
        self.requests = []

    async def request(self, command, arguments=None, **options):
        self.requests.append((command, arguments))
        return {'breakpoints': [{'verified': True}]}


async def test_dap_payload_without_options_is_unchanged(tmp_path):
    session = PythonDebugSession()
    session.profile = CodeProject('payload', tmp_path, ('python3', 'main.py'))
    session._client = RecordingClient()
    await session.set_breakpoints(str(tmp_path / 'main.py'), (4, 2))
    await session.set_breakpoints(str(tmp_path / 'main.py'), (2, 4), {
        2: BreakpointOptions(condition='x > 1'), 4: BreakpointOptions(log_message='x={x}'),
        9: BreakpointOptions(condition='not requested')})
    path = str(tmp_path / 'main.py')
    assert session._client.requests == [
        ('setBreakpoints', {'source': {'path': path},
                            'breakpoints': [{'line': 2}, {'line': 4}], 'sourceModified': False}),
        ('setBreakpoints', {'source': {'path': path}, 'breakpoints': [
            {'line': 2, 'condition': 'x > 1'}, {'line': 4, 'logMessage': 'x={x}'}],
            'sourceModified': False}),
    ]


@pytest.mark.parametrize(('options', 'expected'), [
    (None, ''),
    (BreakpointOptions(condition='a > 1'), 'a > 1'),
    (BreakpointOptions(log_message='hit {a.b} done'),
     'console.log(`hit ${(a.b)} done`), false'),
    (BreakpointOptions(condition='ok', log_message='v={v}'),
     '(ok) && (console.log(`v=${(v)}`), false)'),
    (BreakpointOptions(log_message='tick `$x` \\ {open'),
     'console.log(`tick \\`\\$x\\` \\\\ {open`), false'),
    (BreakpointOptions(log_message='empty {} braces'),
     'console.log(`empty {} braces`), false'),
    (BreakpointOptions(log_message='nested { {a: 1}.a } end'),
     'console.log(`nested ${( {a: 1}.a )} end`), false'),
    (BreakpointOptions(log_message='open {x and } then {y}'),
     'console.log(`open ${(x and )} then ${(y)}`), false'),
    (BreakpointOptions(log_message='unclosed {x'),
     'console.log(`unclosed {x`), false'),
], ids=['none', 'condition', 'logpoint', 'both', 'escaped', 'empty-braces', 'nested-braces',
        'two-placeholders', 'unclosed'])
def test_node_condition_expresses_conditions_and_logpoints(options, expected):
    from debugpilot.debugger.node import cdp_condition

    assert cdp_condition(options) == expected


@pytest.mark.parametrize('session_type', ['GoAttachSession', 'PythonAttachSession'])
async def test_attach_sends_options_with_the_mapped_remote_path(tmp_path, session_type):
    from pathlib import PurePosixPath

    import debugpilot.debugger as debugger

    session = getattr(debugger, session_type)()
    source = tmp_path / 'pkg' / 'main.py'
    source.parent.mkdir()
    source.write_text('pass\n')
    session.profile = CodeProject('attach', tmp_path, ())
    session._local_root = tmp_path.resolve()
    session._remote_root = PurePosixPath('/app')
    session._client = RecordingClient()
    await session.set_breakpoints(str(source), (1,), {
        1: BreakpointOptions(condition='ready', log_message='value {v}')})
    assert session._client.requests == [('setBreakpoints', {
        'source': {'path': '/app/pkg/main.py'},
        'breakpoints': [{'line': 1, 'condition': 'ready', 'logMessage': 'value {v}'}],
        'sourceModified': False,
    })]
    key = str(source.resolve())
    assert session.breakpoint_options[key] == {
        1: BreakpointOptions(condition='ready', log_message='value {v}')}


async def test_real_node_logpoint_with_nested_braces_logs(tmp_path):
    profile, source, line = program(tmp_path, 'node')
    output = []
    session = NodeDebugSession(on_output=lambda category, text: output.append(text))
    try:
        await session.start(profile, {str(source): (line,)}, {
            str(source): {line: BreakpointOptions(log_message='i={ {v: i}.v } {}')}})
        name, _ = await next_event(session, 'stopped', 'terminated')
        assert name == 'terminated'
        text = ''.join(output)
        for value in range(5):
            assert f'i={value} {{}}' in text
    finally:
        await session.close()
