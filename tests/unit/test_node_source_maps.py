"""Compiled TypeScript through source maps, with a real Node Inspector."""

import asyncio
import json
import os

import pytest
from test_source_maps import encode

from debugpilot.debugger import NodeDebugSession
from debugpilot.storage.code_projects import CodeProject

MAIN_TS = ('import { twice } from "./lib";\ninterface Box { v: number }\n'
           'const box: Box = { v: 20 };\nconst result: number = twice(box.v) + 2;\n'
           'console.log(`RESULT:${result}`);\n')
LIB_TS = ('export function twice(n: number): number {\n  const doubled = n * 2;\n'
          '  return doubled;\n}\n')
PRELUDE = '"use strict";\nObject.defineProperty(exports, "__esModule", { value: true });\n'
MAIN_JS = (PRELUDE + 'const lib_1 = require("./lib");\nconst box = { v: 20 };\n'
           'const result = (0, lib_1.twice)(box.v) + 2;\nconsole.log(`RESULT:${result}`);\n'
           '//# sourceMappingURL=main.js.map\n')
LIB_JS = (PRELUDE + 'exports.twice = twice;\nfunction twice(n) {\n    const doubled = n * 2;\n'
          '    return doubled;\n}\n//# sourceMappingURL=lib.js.map\n')
# Like tsc: two prelude lines, then each statement maps to its .ts line (0-based here).
MAIN_MAP = [[], [], [(0, 0, 0, 0)], [(0, 0, 2, 0)], [(0, 0, 3, 0)], [(0, 0, 4, 0)]]
LIB_MAP = [[], [], [], [(0, 0, 0, 0)], [(4, 0, 1, 2)], [(4, 0, 2, 2)], [(0, 0, 3, 0)]]


def compiled_project(root):
    (root / 'src').mkdir()
    (root / 'dist').mkdir()
    (root / 'src/main.ts').write_text(MAIN_TS)
    (root / 'src/lib.ts').write_text(LIB_TS)
    for name, code, lines in (('main', MAIN_JS, MAIN_MAP), ('lib', LIB_JS, LIB_MAP)):
        (root / f'dist/{name}.js').write_text(code)
        (root / f'dist/{name}.js.map').write_text(json.dumps({
            'version': 3, 'file': f'{name}.js', 'sources': [f'../src/{name}.ts'],
            'names': [], 'mappings': encode(lines)}))
    return (root / 'src/main.ts').resolve(), (root / 'src/lib.ts').resolve()


async def event(session, *names):
    async with asyncio.timeout(20):
        while True:
            message = await session.events.get()
            if message.get('event') in names:
                return message.get('event'), message.get('body', {})


async def locals_of(session, frame):
    scopes = await session.scopes(frame['id'])
    return {v['name']: v['value'] for scope in scopes if not scope['expensive']
            for v in await session.variables(scope['variablesReference'])}


async def test_breakpoints_on_ts_lines_stop_in_compiled_code_and_frames_map_back(tmp_path):
    main_ts, lib_ts = compiled_project(tmp_path)
    output = []
    profile = CodeProject('tsc', tmp_path, ('node', 'dist/main.js'))
    session = NodeDebugSession(on_output=lambda category, text: output.append((category, text)))
    try:
        # main.ts:2 is an interface: no generated code, so it stays unverified.
        await session.start(profile, {main_ts: [4, 2], lib_ts: [2]})
        assert await event(session, 'stopped') == ('stopped', {'threadId': 1})
        frames = await session.stack()
        assert (frames[0]['source']['path'], frames[0]['line']) == (str(main_ts), 4)
        await session.continue_execution()
        await event(session, 'stopped')
        # lib.js loaded after the breakpoints were set; the stop is still on lib.ts:2.
        frames = await session.stack()
        assert (frames[0]['name'], frames[0]['source']['path'], frames[0]['line']) == (
            'twice', str(lib_ts), 2)
        assert (frames[1]['source']['path'], frames[1]['line']) == (str(main_ts), 4)
        assert (await locals_of(session, frames[0]))['n'] == '20'
        entries = session.verified_breakpoints[str(main_ts)]
        assert {e['line']: e['verified'] for e in entries} == {2: False, 4: True}
        assert [(e['line'], e['verified']) for e in session.verified_breakpoints[str(lib_ts)]] == [
            (2, True)]
        await session.continue_execution()
        name, body = await event(session, 'exited')
        assert body['exitCode'] == 0
        assert ''.join(t for c, t in output if c == 'stdout') == 'RESULT:42\n'
    finally:
        await session.close()
    assert session.verified_breakpoints == {}


async def test_javascript_breakpoints_without_maps_are_unchanged(tmp_path):
    main_ts, _ = compiled_project(tmp_path)
    for path in tmp_path.glob('dist/*.map'):
        path.unlink()
    profile = CodeProject('tsc', tmp_path, ('node', 'dist/main.js'))
    session = NodeDebugSession()
    try:
        generated = (tmp_path / 'dist/main.js').resolve()
        await session.start(profile, {generated: [5], main_ts: [4]})
        await event(session, 'stopped')
        frames = await session.stack()
        assert (frames[0]['source']['path'], frames[0]['line']) == (str(generated), 5)
        # Without a map a .ts breakpoint is set by URL on the .ts file and never binds.
        assert not session.verified_breakpoints[str(main_ts)][0]['verified']
    finally:
        await session.close()


@pytest.mark.skipif(os.name == 'nt', reason='the remote root must be a POSIX path')
async def test_attach_maps_ts_breakpoints_through_remote_root(tmp_path):
    import re

    from debugpilot.debugger.node_attach import NodeAttachSession
    from debugpilot.storage.code_projects import RemoteAttach

    remote, local = tmp_path.resolve() / 'remote', tmp_path.resolve() / 'local'
    remote.mkdir()
    local.mkdir()
    compiled_project(remote)
    main_ts, lib_ts = compiled_project(local)
    target = await asyncio.create_subprocess_exec(
        'node', '--inspect-brk=127.0.0.1:0', str(remote / 'dist/main.js'),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    async with asyncio.timeout(15):
        while not (match := re.match(rb'Debugger listening on ws://127\.0\.0\.1:(\d+)/',
                                     await target.stderr.readline())):
            pass
    profile = CodeProject('attach', local, (),
                          node_attach=RemoteAttach('127.0.0.1', int(match[1]), str(remote)))
    session = NodeAttachSession(timeout=15)
    try:
        await session.start(profile, {lib_ts: [2], main_ts: [4]})
        await event(session, 'stopped')  # --inspect-brk stops on the first line.
        await session.continue_execution()
        await event(session, 'stopped')
        frames = await session.stack()
        assert (frames[0]['source']['path'], frames[0]['line']) == (str(main_ts), 4)
        await session.continue_execution()
        await event(session, 'stopped')
        frames = await session.stack()
        assert (frames[0]['source']['path'], frames[0]['line']) == (str(lib_ts), 2)
        assert (await locals_of(session, frames[0]))['n'] == '20'
        assert [(e['line'], e['verified']) for e in session.verified_breakpoints[str(lib_ts)]] == [
            (2, True)]
    finally:
        await session.close()
        target.kill()
        await target.wait()


async def test_native_ts_launch_ignores_maps_of_a_stale_build(tmp_path):
    # node src/main.ts runs the .ts itself, so a dist/ build must not redirect its breakpoints.
    _, lib_ts = compiled_project(tmp_path)
    (tmp_path / 'src/run.ts').write_text('import { twice } from "./lib.ts";\n'
                                         'console.log(`RESULT:${twice(5)}`);\n')
    (tmp_path / 'src/lib.ts').write_text(LIB_TS)
    profile = CodeProject('native', tmp_path, ('node', 'src/run.ts'))
    session = NodeDebugSession()
    try:
        await session.start(profile, {lib_ts: [2]})
        await event(session, 'stopped')
        frames = await session.stack()
        assert (frames[0]['source']['path'], frames[0]['line']) == (str(lib_ts), 2)
        assert (await locals_of(session, frames[0]))['n'] == '5'
    finally:
        await session.close()
