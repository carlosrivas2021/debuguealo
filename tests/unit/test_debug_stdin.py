"""Program input while debugging: the debuggee reads the session's PTY."""

import asyncio
import os
from types import SimpleNamespace

import pytest

from debugpilot.debugger import DebugError, GoDebugSession, NodeDebugSession, PythonDebugSession
from debugpilot.debugger.node_attach import NodeAttachSession
from debugpilot.debugger.remote_attach import RemoteAttachSession
from debugpilot.storage.code_projects import CodeProject
from debugpilot.terminal.session import TerminalSession

PROGRAMS = {
    'python': ('main.py', ('python3', '-u', 'main.py'),
               'name = input("name? ")\nprint(f"HELLO:{name}", flush=True)\n'
               'import sys\nrest = sys.stdin.read()\nprint(f"REST:{rest.strip()}", flush=True)\n'),
    'go': ('main.go', ('go', 'run', 'main.go'),
           'package main\n\nimport (\n\t"bufio"\n\t"fmt"\n\t"io"\n\t"os"\n\t"strings"\n)\n\n'
           'func main() {\n\treader := bufio.NewReader(os.Stdin)\n'
           '\tname, _ := reader.ReadString(10)\n'
           '\tfmt.Printf("HELLO:%s\\n", strings.TrimSpace(name))\n'
           '\trest, _ := io.ReadAll(reader)\n'
           '\tfmt.Printf("REST:%s\\n", strings.TrimSpace(string(rest)))\n}\n'),
    'node': ('main.js', ('node', 'main.js'),
             'const rl = require("readline").createInterface({ input: process.stdin });\n'
             'const lines = [];\nrl.on("line", (l) => lines.push(l));\n'
             'rl.on("close", () => { console.log(`HELLO:${lines[0]}`);\n'
             '  console.log(`REST:${lines.slice(1).join(" ")}`); });\n'),
}
SESSIONS = {'python': PythonDebugSession, 'go': GoDebugSession, 'node': NodeDebugSession}


async def poll(condition, seconds=120):
    """Wait until condition() holds, failing after `seconds`."""
    for _ in range(int(seconds / 0.05)):
        if condition():
            return
        await asyncio.sleep(0.05)
    raise AssertionError('condition not met in time')


async def output_contains(output, text):
    await poll(lambda: text in ''.join(output))


async def wait_running(session):
    await poll(lambda: session.state == 'running')


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_input_lines_and_end_of_input_reach_the_debugged_program(tmp_path, language):
    name, command, text = PROGRAMS[language]
    (tmp_path / name).write_text(text)
    if language == 'go':
        (tmp_path / 'go.mod').write_text('module example.invalid/stdin\n\ngo 1.22\n')
    output = []
    session = SESSIONS[language](on_output=lambda category, chunk: output.append(chunk))
    assert session.supports_input
    try:
        await session.start(CodeProject(language, tmp_path, command), {})
        await wait_running(session)
        if language == 'python':
            await output_contains(output, 'name? ')
        else:
            await asyncio.sleep(1)  # Let the program reach its read.
        session.send_input('ana')
        if language != 'node':
            await output_contains(output, 'HELLO:ana')
        session.send_input('b c')
        session.send_eof()
        await output_contains(output, 'REST:b c')
        assert 'HELLO:ana' in ''.join(output)
    finally:
        await session.close()


@pytest.mark.skipif(os.name == 'nt', reason='reads the POSIX terminal echo flag')
async def test_echo_follows_the_program_terminal_mode(tmp_path):
    (tmp_path / 'main.py').write_text(
        'import getpass\nname = input("name? ")\nprint("ASKED", flush=True)\n'
        'secret = getpass.getpass("pw? ")\nprint(f"LEN:{len(secret)}", flush=True)\n')
    output = []
    session = PythonDebugSession(on_output=lambda category, chunk: output.append(chunk))
    try:
        await session.start(CodeProject('p', tmp_path, ('python3', 'main.py')), {})
        await output_contains(output, 'name? ')
        assert session.input_echo() is True
        session.send_input('ana')
        await output_contains(output, 'ASKED')
        await poll(lambda: not session.input_echo(), seconds=10)
        session.send_input('hunter2')
        await output_contains(output, 'LEN:7')
    finally:
        await session.close()


async def test_node_never_asks_the_ui_to_echo(tmp_path):
    # Node runs in the PTY itself, so the terminal's own echo is already in its output.
    assert NodeDebugSession().input_echo() is False


async def test_input_needs_a_launched_running_session(tmp_path):
    session = PythonDebugSession()
    with pytest.raises(DebugError, match='No running program'):
        session.send_input('x')
    with pytest.raises(DebugError, match='No running program'):
        session.send_eof()
    for attach in (RemoteAttachSession, NodeAttachSession):
        assert attach.supports_input is False
        with pytest.raises(DebugError, match='attached'):
            attach().send_input('x')


async def test_program_input_field_sends_lines_and_end_of_input_from_the_debug_view(
        monkeypatch, tmp_path):
    from test_code_debug_ui import debug_app
    from test_tui_grouping import until
    from textual.widgets import Input, RichLog

    app, roots, _ = debug_app(monkeypatch, tmp_path)
    (roots[0] / 'main.py').write_text(
        'name = input("name? ")\nprint(f"HELLO:{name}", flush=True)\n'
        'import sys\nprint(f"REST:{sys.stdin.read().strip()}", flush=True)\n')

    def output():
        return '\n'.join(str(line.text) for line in app.query_one('#code-debug-output', RichLog)
                         .lines)

    async with app.run_test(size=(140, 52)) as pilot:
        field = app.query_one('#code-debug-input', Input)
        await pilot.click('#area-code')
        assert not field.display  # Nothing to type into before a debug session.
        await pilot.press('shift+f5')
        await until(pilot, lambda: field.display and 'name?' in output())
        field.focus()
        await pilot.press(*'ana', 'enter')
        await until(pilot, lambda: 'HELLO:ana' in output())
        # The program echoes, so the typed line shows in the output like a terminal.
        assert '[one · input] ana' in output()
        assert field.value == ''
        await pilot.press('s')  # Typing in the field never triggers Code shortcuts.
        assert field.value == 's'
        await pilot.press('backspace', *'end', 'ctrl+d')
        await until(pilot, lambda: 'REST:end' in output())
        await until(pilot, lambda: not field.display)  # The program ended.


def test_end_of_input_uses_the_windows_console_sequence():
    # Windows consoles end input with Ctrl+Z then Enter at the start of a line; they
    # ignore the Unix Ctrl+D character.
    written = []
    terminal = TerminalSession(on_output=lambda _text: None)
    terminal.process = SimpleNamespace(write=written.append)
    terminal._closed = False
    terminal._windows = True
    terminal.end_input()
    assert written == ['\x1a\r']


def test_unknown_echo_hides_typed_input():
    # Windows cannot report the terminal's echo mode, and a getpass prompt there must
    # not end up in the debug output, so unknown hides typed lines.
    session = PythonDebugSession()
    session._adapter = SimpleNamespace(echo_enabled=lambda: None)
    assert session.input_echo() is False
