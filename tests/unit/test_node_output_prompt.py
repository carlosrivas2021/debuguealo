import asyncio

from debugpilot.debugger import NodeDebugSession


def recording():
    output = []
    session = NodeDebugSession(on_output=lambda category, text: output.append((category, text)))
    return session, output


async def test_a_prompt_without_newline_shows_once_the_program_waits():
    # readline writes 'name? ' and waits for input with no newline (ConPTY of pywinpty 3).
    session, output = recording()
    session._output('\x1b[1G\x1b[0Jname? \x1b[7G')
    await asyncio.sleep(0.3)
    assert output == [('stdout', 'name? ')]
    session._output('Ana\r\nhello Ana\r\n')
    assert output[1:] == [('stdout', 'Ana\n'), ('stdout', 'hello Ana\n')]


async def test_a_line_split_across_chunks_is_still_one_line():
    session, output = recording()
    session._output('Debugger listening on ws://127.0.0.1:9229/')
    session._output('0f0e0d0c-0b0a-4908-8706-050403020100\r\n')
    await asyncio.sleep(0.3)
    assert session._url == 'ws://127.0.0.1:9229/0f0e0d0c-0b0a-4908-8706-050403020100'
    assert output == []


async def test_a_line_of_only_cursor_moves_adds_nothing():
    # ConPTY ends a program with cursor moves such as '\x1b[6;1H\r\n'; an empty line the
    # program prints still shows.
    session, output = recording()
    session._output('hello Ana\r\n\x1b[6;1H\r\n')
    session._output('\r\n')
    await asyncio.sleep(0.3)
    assert output == [('stdout', 'hello Ana\n'), ('stdout', '\n')]
