"""Watch evaluation through each real debug adapter."""

import asyncio

import pytest
from test_breakpoint_options_debug import SESSIONS, next_event, program

from debugpilot.debugger import DebugError


async def paused(tmp_path, language):
    profile, source, line = program(tmp_path, language)
    session = SESSIONS[language]()
    await session.start(profile, {str(source): (line,)})
    name, _ = await next_event(session, 'stopped', 'terminated')
    assert name == 'stopped'
    return session, (await session.stack())[0], source


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_evaluate_returns_the_value_in_the_paused_frame(tmp_path, language):
    session, frame, _ = await paused(tmp_path, language)
    try:
        assert await session.evaluate('i + 10', frame['id']) == '10'
        assert await session.evaluate('total', frame['id']) == '0'
    finally:
        await session.close()


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_evaluate_reports_the_debugger_error(tmp_path, language):
    session, frame, _ = await paused(tmp_path, language)
    try:
        with pytest.raises(DebugError) as raised:
            await session.evaluate('missing_name', frame['id'])
        assert 'missing_name' in str(raised.value)
        # One failing expression leaves the session usable.
        assert await session.evaluate('i', frame['id']) == '0'
    finally:
        await session.close()


@pytest.mark.parametrize('language', ['python', 'node'])
async def test_evaluate_requires_a_pause(tmp_path, language):
    session, frame, source = await paused(tmp_path, language)
    try:
        # Without the loop breakpoint the program runs to its end.
        await session.set_breakpoints(str(source), ())
        await session.continue_execution()
        await asyncio.wait_for(next_event(session, 'terminated'), 60)
        with pytest.raises(DebugError, match='Pause at a breakpoint'):
            await session.evaluate('i', frame['id'])
    finally:
        await session.close()
