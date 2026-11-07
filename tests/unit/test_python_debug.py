"""Public backend contract, including required real-debugpy proof (never silently skipped)."""

import asyncio
import sys
import venv

import pytest

from debugpilot.debugger import DebugError, PythonDebugSession
from debugpilot.storage.code_projects import CodeProject


async def event(session, name):
    async with asyncio.timeout(20):
        while True:
            message = await session.events.get()
            if message.get('event') == name:
                return message.get('body', {})


@pytest.mark.parametrize('module', [False, True])
async def test_real_breakpoint_inspection_steps_output_and_exit(tmp_path, module):
    source = tmp_path / 'sample.py'
    source.write_text(
        'def calculate(value):\n'
        '    result = value + 1\n'
        '    return result\n'
        'answer = 41\n'
        'answer = calculate(answer)\n'
        'print(f"RESULT:{answer}", flush=True)\n'
    )
    command = (sys.executable, '-m', 'sample') if module else (
        sys.executable, '-u', 'sample.py'
    )
    profile = CodeProject('sample', tmp_path, command)
    output = []
    session = PythonDebugSession(on_output=lambda category, text: output.append((category, text)))
    try:
        await session.start(profile, {source: {5}})
        await event(session, 'stopped')
        assert session.state == 'stopped'
        assert session.profile == profile
        assert profile.command == command
        assert session.requested_breakpoints == {str(source): (5,)}
        assert session.verified_breakpoints[str(source)][0]['verified'] is True
        frames = await session.stack()
        assert frames[0]['line'] == 5
        scopes = await session.scopes(frames[0]['id'])
        values = await session.variables(scopes[0]['variablesReference'])
        assert any(value['name'] == 'answer' and value['value'] == '41' for value in values)
        await session.step_in()
        await event(session, 'stopped')
        assert (await session.stack())[0]['name'] == 'calculate'
        await session.step_over()
        await event(session, 'stopped')
        await session.step_out()
        await event(session, 'stopped')
        await session.set_breakpoints(source, [])
        assert session.requested_breakpoints[str(source)] == ()
        await session.continue_execution()
        assert (await event(session, 'exited'))['exitCode'] == 0
        await event(session, 'terminated')
        assert ''.join(text for category, text in output if category == 'stdout') == 'RESULT:42\n'
        assert ''.join(text for category, text in output if category == 'stderr') == ''
        assert session.exit_code == 0
    finally:
        await session.close()
        await session.close()
    assert session.state == 'closed'
    assert session.thread_id is None
    assert session.verified_breakpoints == {}


@pytest.mark.parametrize('command', [
    ('npm', 'run', 'dev'), ('python', '-c', 'print("MUST NOT RUN")'),
    ('python', '-X', 'dev', 'sample.py'), ('python',), ('python', '-m'),
    ('python', '-m', 'bad/name'), ('python', '-S', 'sample.py'),
])
async def test_rejected_command_never_executes_or_mutates(tmp_path, command):
    output = []
    profile = CodeProject('unsupported', tmp_path, command)
    session = PythonDebugSession(on_output=lambda *args: output.append(args))
    with pytest.raises(DebugError, match='Supported Python commands:'):
        await session.start(profile, {})
    assert profile.command == command
    assert output == []
    assert session.state == 'idle'
    assert session.profile is None
    assert session.requested_breakpoints == {}
    assert list(tmp_path.iterdir()) == []
    await session.close()


async def test_missing_adapter_is_actionable_without_running_target(tmp_path):
    environment = tmp_path / 'environment'
    await asyncio.to_thread(venv.EnvBuilder(with_pip=False).create, environment)
    interpreter = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    source = tmp_path / 'sample.py'
    marker = tmp_path / 'executed'
    source.write_text(f'from pathlib import Path; Path({str(marker)!r}).touch()\n')
    profile = CodeProject('missing', tmp_path, (str(interpreter), str(source)))
    session = PythonDebugSession(timeout=8)
    with pytest.raises(DebugError, match='install debugpy'):
        await session.start(profile, {})
    assert not marker.exists()
    assert profile.command == (str(interpreter), str(source))
    assert session.state == 'closed'
    assert session.thread_id is None
    await session.close()


async def test_startup_cancellation_closes_owned_adapter(tmp_path):
    # Cancel at a public starting notification, after ownership has been acquired.
    started = asyncio.Event()
    session = PythonDebugSession(on_event=lambda message: (
        started.set() if message.get('event') == 'adapterStarted' else None
    ))
    source = tmp_path / 'sample.py'
    source.write_text('print("MUST NOT RUN")\n')
    task = asyncio.create_task(session.start(
        CodeProject('cancel', tmp_path, (sys.executable, str(source))), {}
    ))
    await asyncio.wait_for(started.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await session.close()
    assert session.state == 'closed'
    assert session.thread_id is None
    assert session.verified_breakpoints == {}


async def test_real_stop_removes_owned_descendants(tmp_path):
    source = tmp_path / 'sample.py'
    ready, marker = tmp_path / 'ready', tmp_path / 'survived'
    child = (
        f'import time; from pathlib import Path; Path({str(ready)!r}).touch(); '
        f'time.sleep(3); Path({str(marker)!r}).touch(); time.sleep(30)'
    )
    source.write_text(
        'import subprocess, sys, time\n'
        f'subprocess.Popen([sys.executable, "-c", {child!r}])\n'
        'time.sleep(30)\n'
    )
    session = PythonDebugSession()
    try:
        await session.start(CodeProject('child', tmp_path, (sys.executable, str(source))), {})
        async with asyncio.timeout(15):
            while not ready.exists():  # noqa: ASYNC110
                await asyncio.sleep(0.02)
        await session.close()
        await session.close()
        await asyncio.sleep(3.2)
        assert not marker.exists()
        assert session.state == 'closed'
    finally:
        await session.close()


async def test_invalid_breakpoint_leaves_intent_unchanged(tmp_path):
    session = PythonDebugSession()
    source = tmp_path / 'sample.py'
    source.write_text('print("not run")\n')
    with pytest.raises(DebugError, match='positive 1-based'):
        profile = CodeProject('bad', tmp_path, (sys.executable, str(source)))
        await session.start(profile, {source: {0}})
    assert session.state == 'idle'
    assert session.requested_breakpoints == {}
    await session.close()
