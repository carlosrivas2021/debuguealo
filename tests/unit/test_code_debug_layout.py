"""Readable debug panel: section titles, dimmed internal frames, one-line values."""

import asyncio

import pytest
from test_code_debug_ui import debug_app
from textual.widgets import DataTable, Static

from debugpilot.debugger import NodeDebugSession
from debugpilot.debugger.node import _display
from debugpilot.storage.code_projects import CodeProject
from debugpilot.tui.code_debug import _frame_cells, _variable_value


async def test_debug_panel_sections_have_titles(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.click('#area-code')
        assert app.query_one('#code-stack', DataTable).border_title == 'Call stack'
        assert app.query_one('#code-watch-pane').border_title == 'Watch'
        assert app.query_one('#code-variables', Static).border_title == 'Variables'


def test_frames_without_source_are_dimmed():
    mine = _frame_cells({'name': 'obtener_mensaje', 'line': 7, 'source': {'path': '/app/a.js'}})
    internal = _frame_cells({'name': 'wrapModuleLoad', 'line': 3, 'source': {}})
    assert [str(cell) for cell in mine] == ['obtener_mensaje', '/app/a.js', '7']
    assert [str(cell) for cell in internal] == ['wrapModuleLoad', '?', '3']
    assert all(cell.style == 'bright_black' for cell in internal)
    assert all(not cell.style for cell in mine)


@pytest.mark.parametrize(('value', 'expected'), [
    ('42', '42'),
    ("function crear_mensaje() {\n  return 'hola';\n}", 'function crear_mensaje() { …'),
    ('x' * 300, 'x' * 199 + '…'),
], ids=['plain', 'multi-line', 'long'])
def test_variable_values_fit_on_one_line(value, expected):
    assert _variable_value(value) == expected


@pytest.mark.parametrize(('remote', 'expected'), [
    ({'type': 'function', 'description': "function crear_mensaje() {\n  return 1;\n}"},
     'ƒ crear_mensaje()'),
    ({'type': 'function', 'description': 'async function cargar(id) {}'}, 'ƒ cargar()'),
    ({'type': 'function', 'description': '(a) => a + 1'}, 'ƒ anonymous()'),
    ({'type': 'function', 'className': 'Function', 'description': 'class Pedido {\n}'},
     'class Pedido'),
    ({'type': 'number', 'description': '41', 'value': 41}, '41'),
], ids=['declaration', 'async', 'arrow', 'class', 'number'])
def test_node_functions_are_shown_by_name(remote, expected):
    assert _display(remote) == expected


async def test_real_node_variables_show_functions_by_name(tmp_path):
    source = tmp_path / 'main.js'
    source.write_text("function helper() {\n  return 1;\n}\nconst answer = helper();\n"
                      "console.log(answer);\n")
    session = NodeDebugSession()
    try:
        await session.start(CodeProject('node', tmp_path, ('node', 'main.js')), {str(source): (4,)})
        async with asyncio.timeout(30):
            while session.state != 'stopped':
                await session.events.get()
        frame = (await session.stack())[0]
        values = {}
        for scope in await session.scopes(frame['id']):
            if not scope['expensive']:
                for variable in await session.variables(scope['variablesReference']):
                    values[variable['name']] = variable['value']
        assert values['helper'] == 'ƒ helper()'
    finally:
        await session.close()
