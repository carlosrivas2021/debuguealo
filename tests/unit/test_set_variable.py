"""Changing a variable of the paused frame through each real debug adapter."""

import pytest
from test_breakpoint_options_debug import SESSIONS, next_event, program
from test_watch_evaluate import paused

from debugpilot.debugger import DebugError


async def scope_of(session, name):
    """(scope reference, value) of a variable in the top frame's inexpensive scopes."""
    frame = (await session.stack())[0]
    for scope in await session.scopes(frame['id']):
        if scope.get('expensive'):
            continue
        for variable in await session.variables(scope['variablesReference']):
            if variable['name'] == name:
                return scope['variablesReference'], variable['value']
    raise AssertionError(f'{name} not found')


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_a_changed_variable_is_what_the_program_uses_next(tmp_path, language):
    output = []
    profile, source, line = program(tmp_path, language)
    session = SESSIONS[language](on_output=lambda category, text: output.append(text))
    try:
        await session.start(profile, {str(source): (line,)})
        name, _ = await next_event(session, 'stopped', 'terminated')
        assert name == 'stopped'
        reference, value = await scope_of(session, 'total')
        assert value == '0'
        assert await session.set_variable(reference, 'total', '100') == '100'
        assert (await scope_of(session, 'total'))[1] == '100'
        await session.set_breakpoints(str(source), ())
        await session.continue_execution()
        await next_event(session, 'terminated')
        assert 'TOTAL:110' in ''.join(output)  # 100 plus 0..4.
    finally:
        await session.close()


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_an_invalid_value_is_refused_and_changes_nothing(tmp_path, language):
    session, _frame, _source = await paused(tmp_path, language)
    try:
        reference, _ = await scope_of(session, 'total')
        with pytest.raises(DebugError):
            await session.set_variable(reference, 'total', 'missing_name')
        assert (await scope_of(session, 'total'))[1] == '0'
    finally:
        await session.close()


async def test_node_changes_a_block_scoped_variable(tmp_path):
    # V8 sets local, closure and catch scopes directly; the loop's `let i` is a block scope.
    output = []
    profile, source, line = program(tmp_path, 'node')
    session = SESSIONS['node'](on_output=lambda category, text: output.append(text))
    try:
        await session.start(profile, {str(source): (line,)})
        await next_event(session, 'stopped')
        reference, value = await scope_of(session, 'i')
        assert value == '0'
        assert await session.set_variable(reference, 'i', '3') == '3'
        await session.set_breakpoints(str(source), ())
        await session.continue_execution()
        await next_event(session, 'terminated')
        assert 'TOTAL:7' in ''.join(output)  # The loop goes on from 3: 3 + 4.
    finally:
        await session.close()


async def test_a_change_needs_a_pause(tmp_path):
    session, _frame, source = await paused(tmp_path, 'python')
    try:
        reference, _ = await scope_of(session, 'total')
        await session.set_breakpoints(str(source), ())
        await session.continue_execution()
        await next_event(session, 'terminated')
        with pytest.raises(DebugError, match='Pause at a breakpoint'):
            await session.set_variable(reference, 'total', '1')
    finally:
        await session.close()
