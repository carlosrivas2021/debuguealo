from debugpilot.tui.code_debug import OutputLines


def test_a_lone_newline_ends_the_open_line_instead_of_adding_an_empty_one():
    # print('hello Ana') can arrive as 'hello Ana' and then '\n' (debugpy on Windows).
    lines = OutputLines()
    assert lines.accept('stdout', 'hello Ana')
    assert not lines.accept('stdout', '\n')
    assert lines.accept('stdout', 'password length 3')
    assert not lines.accept('stdout', '\r\n')


def test_an_empty_line_the_program_writes_still_shows():
    lines = OutputLines()
    assert lines.accept('stdout', 'first\n')
    assert lines.accept('stdout', '\n')
    assert lines.accept('stdout', 'name? ')
    assert lines.accept('stderr', '\n')  # Each stream keeps its own open line.
