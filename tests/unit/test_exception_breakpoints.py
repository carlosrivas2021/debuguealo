"""Pausing on exceptions through the public session API, against real adapters."""

import asyncio
import sys

import pytest

from debugpilot.debugger import DebugError, GoDebugSession, NodeDebugSession, PythonDebugSession
from debugpilot.storage.code_projects import CodeProject


async def next_of(session, names, seconds=120):
    """The first of the named events; output and state events are skipped."""
    async with asyncio.timeout(seconds):
        while True:
            message = await session.events.get()
            if message.get('event') in names:
                return message.get('event'), message.get('body', {})


PYTHON_UNCAUGHT = (
    'def parse(text):\n'
    '    return int(text)\n'
    'parse("abc")\n'
)
PYTHON_CAUGHT = (
    'try:\n'
    '    raise KeyError("missing")\n'
    'except KeyError:\n'
    '    pass\n'
    'print("DONE", flush=True)\n'
)


def python_project(tmp_path, source):
    (tmp_path / 'sample.py').write_text(source)
    return CodeProject('sample', tmp_path, (sys.executable, '-u', 'sample.py'))


async def test_python_pauses_on_an_uncaught_exception_by_default(tmp_path):
    session = PythonDebugSession()
    assert session.exception_mode == 'uncaught'
    try:
        await session.start(python_project(tmp_path, PYTHON_UNCAUGHT), {})
        name, body = await next_of(session, {'stopped', 'exited'}, 20)
        assert (name, body.get('reason')) == ('stopped', 'exception')
        info = await session.exception_info()
        assert info.startswith('ValueError')
        assert "invalid literal for int() with base 10: 'abc'" in info
        assert (await session.stack())[0]['line'] == 2
        await session.continue_execution()
        name, body = await next_of(session, {'stopped', 'exited'}, 20)
        assert (name, body.get('exitCode')) == ('exited', 1)
    finally:
        await session.close()


@pytest.mark.parametrize(('mode', 'pauses'), [('uncaught', False), ('all', True)])
async def test_python_caught_exception_pauses_only_in_all_mode(tmp_path, mode, pauses):
    session = PythonDebugSession()
    session.exception_mode = mode
    try:
        await session.start(python_project(tmp_path, PYTHON_CAUGHT), {})
        name, body = await next_of(session, {'stopped', 'exited'}, 20)
        if pauses:
            assert (name, body.get('reason')) == ('stopped', 'exception')
            assert (await session.exception_info()).startswith('KeyError')
            assert (await session.stack())[0]['line'] == 2
        else:
            assert (name, body.get('exitCode')) == ('exited', 0)
    finally:
        await session.close()


async def test_python_none_mode_lets_the_crash_end_the_process(tmp_path):
    session = PythonDebugSession()
    session.exception_mode = 'none'
    try:
        await session.start(python_project(tmp_path, PYTHON_UNCAUGHT), {})
        name, body = await next_of(session, {'stopped', 'exited'}, 20)
        assert (name, body.get('exitCode')) == ('exited', 1)
    finally:
        await session.close()


async def test_python_mode_changes_apply_to_the_live_session(tmp_path):
    source = tmp_path / 'sample.py'
    session = PythonDebugSession()
    session.exception_mode = 'none'
    try:
        await session.start(python_project(tmp_path, PYTHON_CAUGHT), {source: [1]})
        name, _ = await next_of(session, {'stopped', 'exited'}, 20)
        assert name == 'stopped'
        await session.set_exception_mode('all')
        assert session.exception_mode == 'all'
        await session.continue_execution()
        name, body = await next_of(session, {'stopped', 'exited'}, 20)
        assert (name, body.get('reason')) == ('stopped', 'exception')
    finally:
        await session.close()


async def test_unknown_mode_is_rejected_without_changing_the_session():
    session = PythonDebugSession()
    with pytest.raises(DebugError, match='Unknown exception mode'):
        await session.set_exception_mode('sometimes')
    assert session.exception_mode == 'uncaught'


def go_project(tmp_path, body):
    (tmp_path / 'go.mod').write_text('module example.invalid/debugpilot\n\ngo 1.22\n')
    (tmp_path / 'main.go').write_text(body)
    return CodeProject('Go sample', tmp_path, ('go', 'run', 'main.go'))


GO_PANIC = 'package main\nfunc main() {\n panic("boom")\n}\n'


async def test_go_pauses_on_an_unrecovered_panic(tmp_path):
    session = GoDebugSession()
    try:
        await session.start(go_project(tmp_path, GO_PANIC), {})
        name, body = await next_of(session, {'stopped', 'exited', 'terminated'})
        assert (name, body.get('reason')) == ('stopped', 'exception')
        assert 'boom' in await session.exception_info()
    finally:
        await session.close()


async def test_go_none_mode_lets_the_panic_end_the_process(tmp_path):
    session = GoDebugSession()
    session.exception_mode = 'none'
    try:
        await session.start(go_project(tmp_path, GO_PANIC), {})
        name, _ = await next_of(session, {'stopped', 'exited', 'terminated'})
        assert name in {'exited', 'terminated'}
    finally:
        await session.close()


NODE_UNCAUGHT = 'function parse(text) {\n  throw new TypeError(`bad ${text}`);\n}\nparse("abc");\n'
NODE_CAUGHT = 'try {\n  throw new RangeError("caught");\n} catch (e) {}\nconsole.log("DONE");\n'


def node_project(tmp_path, source):
    (tmp_path / 'app.js').write_text(source)
    return CodeProject('node', tmp_path, ('node', 'app.js'))


async def test_node_pauses_on_an_uncaught_exception_by_default(tmp_path):
    session = NodeDebugSession()
    try:
        await session.start(node_project(tmp_path, NODE_UNCAUGHT), {})
        name, body = await next_of(session, {'stopped', 'exited'}, 20)
        assert (name, body.get('reason')) == ('stopped', 'exception')
        assert (await session.exception_info()).startswith('TypeError: bad abc')
        assert (await session.stack())[0]['line'] == 2
    finally:
        await session.close()


@pytest.mark.parametrize(('mode', 'pauses'), [('uncaught', False), ('all', True)])
async def test_node_caught_exception_pauses_only_in_all_mode(tmp_path, mode, pauses):
    session = NodeDebugSession()
    session.exception_mode = mode
    try:
        await session.start(node_project(tmp_path, NODE_CAUGHT), {})
        name, body = await next_of(session, {'stopped', 'exited'}, 20)
        if pauses:
            assert (name, body.get('reason')) == ('stopped', 'exception')
            assert (await session.exception_info()).startswith('RangeError: caught')
        else:
            assert (name, body.get('exitCode')) == ('exited', 0)
    finally:
        await session.close()


async def test_node_none_mode_lets_the_crash_end_the_process(tmp_path):
    session = NodeDebugSession()
    session.exception_mode = 'none'
    try:
        await session.start(node_project(tmp_path, NODE_UNCAUGHT), {})
        name, body = await next_of(session, {'stopped', 'exited'}, 20)
        assert (name, body.get('exitCode')) == ('exited', 1)
    finally:
        await session.close()
