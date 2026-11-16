"""Nested variables (object fields, dict entries) through each real debug adapter."""

import pytest
from test_breakpoint_options_debug import SESSIONS, next_event

from debugpilot.debugger import DebugError
from debugpilot.storage.code_projects import CodeProject

# Each program pauses on BREAK_LINE with config.port = 80 and config.point.x = 1,
# then prints RESULT:<port>:<x>.
PROGRAMS = {
    'python': ('main.py', ('python3', '-u', 'main.py'), 6,
               'class Point:\n    def __init__(self):\n        self.x = 1\n'
               "config = {'port': 80, 'point': Point()}\n"
               'ready = True\n'
               'print("READY", flush=True)\n'
               "print(f\"RESULT:{config['port']}:{config['point'].x}\", flush=True)\n"),
    'go': ('main.go', ('go', 'run', 'main.go'), 14,
           'package main\n\nimport "fmt"\n\n'
           'type Point struct{ X int }\n\n'
           'type Config struct {\n\tPort  int\n\tPoint Point\n}\n\n'
           'func main() {\n'
           '\tconfig := Config{Port: 80, Point: Point{X: 1}}\n'
           '\tfmt.Printf("RESULT:%d:%d\\n", config.Port, config.Point.X)\n}\n'),
    'node': ('main.js', ('node', 'main.js'), 2,
             'const config = { port: 80, point: { x: 1 } };\n'
             'console.log("READY");\n'
             'console.log(`RESULT:${config.port}:${config.point.x}`);\n'),
}
# The field names as each adapter reports them.
NAMES = {
    'python': ('config', "'port'", "'point'", 'x'),
    'go': ('config', 'Port', 'Point', 'X'),
    'node': ('config', 'port', 'point', 'x'),
}


def program(tmp_path, language):
    name, command, line, text = PROGRAMS[language]
    source = tmp_path / name
    source.write_text(text)
    if language == 'go':
        (tmp_path / 'go.mod').write_text('module example.invalid/nested\n\ngo 1.22\n')
    return CodeProject(language, tmp_path, command), source, line


async def child(session, reference, name):
    """The variable called name among the children of reference."""
    for variable in await session.variables(reference):
        if variable['name'] == name:
            return variable
    raise AssertionError(f'{name} not found')


async def top(session, name):
    frame = (await session.stack())[0]
    for scope in await session.scopes(frame['id']):
        if scope.get('expensive'):
            continue
        for variable in await session.variables(scope['variablesReference']):
            if variable['name'] == name:
                return variable
    raise AssertionError(f'{name} not found')


async def start(tmp_path, language, output):
    profile, source, line = program(tmp_path, language)
    session = SESSIONS[language](on_output=lambda category, text: output.append(text))
    await session.start(profile, {str(source): (line,)})
    name, _ = await next_event(session, 'stopped', 'terminated')
    assert name == 'stopped'
    return session, source


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_nested_fields_are_listed_and_changed(tmp_path, language):
    output = []
    session, source = await start(tmp_path, language, output)
    config_name, port_name, point_name, x_name = NAMES[language]
    try:
        config = await top(session, config_name)
        assert config['variablesReference'] > 0
        port = await child(session, config['variablesReference'], port_name)
        assert port['value'] == '80'
        point = await child(session, config['variablesReference'], point_name)
        assert point['variablesReference'] > 0
        assert (await child(session, point['variablesReference'], x_name))['value'] == '1'

        assert await session.set_variable(
            config['variablesReference'], port_name, '8080') == '8080'
        assert await session.set_variable(point['variablesReference'], x_name, '7') == '7'
        # The pane reads the frame again after a change and sees the new values.
        config = await top(session, config_name)
        port = await child(session, config['variablesReference'], port_name)
        assert port['value'] == '8080'

        await session.set_breakpoints(str(source), ())
        await session.continue_execution()
        await next_event(session, 'terminated')
        assert 'RESULT:8080:7' in ''.join(output)
    finally:
        await session.close()


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_an_invalid_nested_value_is_refused_and_changes_nothing(tmp_path, language):
    session, _source = await start(tmp_path, language, [])
    config_name, port_name, point_name, x_name = NAMES[language]
    try:
        config = await top(session, config_name)
        with pytest.raises(DebugError):
            await session.set_variable(config['variablesReference'], port_name, 'missing_name')
        point = await child(session, config['variablesReference'], point_name)
        with pytest.raises(DebugError):
            await session.set_variable(point['variablesReference'], x_name, 'missing_name')
        config = await top(session, config_name)
        assert (await child(session, config['variablesReference'], port_name))['value'] == '80'
        point = await child(session, config['variablesReference'], point_name)
        assert (await child(session, point['variablesReference'], x_name))['value'] == '1'
    finally:
        await session.close()


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_copy_text_is_the_whole_value_in_the_language_or_a_tree(tmp_path, language):
    from debugpilot.tui.code_debug import VariableRow, copy_text

    session, _source = await start(tmp_path, language, [])
    config_name, port_name, point_name, x_name = NAMES[language]
    try:
        config = await top(session, config_name)
        frame_id = (await session.stack())[0]['id']
        row = VariableRow('Locals', 0, config_name, config['value'],
                          children=config['variablesReference'],
                          expression=config.get('evaluateName', ''))
        text = await copy_text(session, row, frame_id)
        if language == 'python':  # Python's own repr, nothing shortened.
            assert text == "{'port': 80, 'point': Point(x=1)}"
        elif language == 'node':  # JSON, ready to paste.
            assert text == '{\n  "port": 80,\n  "point": {\n    "x": 1\n  }\n}'
        else:  # Delve cannot serialize: the fields as an indented tree.
            lines = text.splitlines()
            assert lines[0] == f"{config_name} = {config['value']}"
            assert f'  {port_name} = 80' in lines
            assert f'    {x_name} = 1' in lines
            assert any(line.startswith(f'  {point_name} = ') for line in lines)
    finally:
        await session.close()
