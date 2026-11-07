import asyncio
import json
import shutil
import sys

import pytest

from debugpilot.terminal.code_session import CodeSession


async def wait_for(predicate, seconds=10):
    async with asyncio.timeout(seconds):
        while not predicate():  # noqa: ASYNC110 — poll observable process/file effects
            await asyncio.sleep(0.02)


async def test_code_command_interactive_status_and_rerun(tmp_path):
    output = []
    exits = []
    session = CodeSession(output.append, lambda: exits.append(session.exit_code))
    script = (
        "import os,sys; print(os.getcwd(),flush=True); print('PROMPT',flush=True); "
        "print('GOT:'+input(),flush=True); sys.exit(7)"
    )
    try:
        await session.open_command((sys.executable, '-u', '-c', script), tmp_path)
        await wait_for(lambda: 'PROMPT' in ''.join(output))
        session.write('hello\r')
        await wait_for(lambda: bool(exits))
        assert 'GOT:hello' in ''.join(output)
        assert str(tmp_path) in ''.join(output)
        assert exits == [7]
        output.clear()
        await session.open_command((sys.executable, '-c', "print('SECOND',flush=True)"), tmp_path)
        await wait_for(lambda: len(exits) == 2)
        assert exits == [7, 0]
        assert 'SECOND' in ''.join(output)
        assert 'GOT:' not in ''.join(output)
    finally:
        await session.close_session()


async def test_code_missing_executable_does_not_start(tmp_path):
    session = CodeSession(lambda text: None)
    with pytest.raises(RuntimeError, match='not found'):
        await session.open_command(('debugpilot-missing-program-12345',), tmp_path)
    assert session.process is None
    await session.close_session()


@pytest.mark.parametrize('finish', ['stop', 'natural'])
async def test_code_descendants_are_removed(tmp_path, finish):
    marker = tmp_path / 'survived'
    ready = tmp_path / 'ready'
    child = (
        f"import time; from pathlib import Path; Path({str(ready)!r}).touch(); "
        f"time.sleep(2); Path({str(marker)!r}).touch(); time.sleep(20)"
    )
    parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); "
    parent += 'time.sleep(30)' if finish == 'stop' else 'time.sleep(0.5)'
    exits = []
    session = CodeSession(lambda text: None, lambda: exits.append(session.exit_code))
    try:
        await session.open_command((sys.executable, '-c', parent, child), tmp_path)
        await wait_for(ready.exists)
        if finish == 'stop':
            await session.close_session()
        await wait_for(lambda: bool(exits))
        assert exits == ([None] if finish == 'stop' else [0])
        await asyncio.sleep(2.2)
        assert not marker.exists()
    finally:
        await session.close_session()


@pytest.mark.parametrize('runtime', ['node', 'npm', 'go'])
@pytest.mark.parametrize('stop', [False, True])
async def test_code_runtime_samples(tmp_path, runtime, stop):
    if not shutil.which(runtime):
        pytest.skip(f'{runtime} is not installed')
    if runtime == 'node':
        script = "console.log('SAMPLE');" + ("setInterval(()=>{},1000)" if stop else "")
        argv = ('node', '-e', script)
    elif runtime == 'npm':
        (tmp_path / 'package.json').write_text(json.dumps({'scripts': {'dev': 'node sample.js'}}))
        (tmp_path / 'sample.js').write_text(
            "console.log('SAMPLE');" + ("setInterval(()=>{},1000)" if stop else "")
        )
        argv = ('npm', 'run', 'dev')
    else:
        (tmp_path / 'main.go').write_text(
            'package main\nimport "fmt"\nfunc main(){fmt.Println("SAMPLE");'
            + ('var s string; fmt.Scanln(&s)' if stop else '') + '}\n'
        )
        argv = ('go', 'run', 'main.go')
    output = []
    exits = []
    session = CodeSession(output.append, lambda: exits.append(session.exit_code))
    try:
        await session.open_command(argv, tmp_path)
        if stop:
            await wait_for(lambda: 'SAMPLE' in ''.join(output), seconds=90)
            await session.close_session()
            assert exits == [None]
            assert session.process is None
        else:
            await wait_for(lambda: bool(exits), seconds=90 if runtime == 'go' else 10)
            assert exits == [0], ''.join(output)
        assert 'SAMPLE' in ''.join(output)
    finally:
        await session.close_session()
