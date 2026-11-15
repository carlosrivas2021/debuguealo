"""A debugged program's terminal output as debug output lines, the way a terminal shows it."""

import asyncio
import contextlib
import re

ANSI = re.compile(r'\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]')
# An escape sequence cut off at the end of a chunk.
PARTIAL_ESCAPE = re.compile(r'\x1b(?:\[[0-?]*[ -/]*|\][^\x07]*)?$')
# Seconds a line without newline waits for the rest before showing (a prompt).
PARTIAL_LINE_DELAY = 0.1
MAX_LINE = 65536


class TerminalLines:
    """Splits terminal output into lines without escape sequences.

    ``on_line`` gets each complete line. A prompt such as ``name? `` has no newline and
    waits for input, so ``on_partial`` gets a partial line once no more output follows
    for a moment. A line of only cursor moves (ConPTY's ``ESC[6;1H``) is no output.
    """

    def __init__(self, on_line, on_partial):
        self._on_line = on_line
        self._on_partial = on_partial
        self._buffer = ''
        self._timer = None

    def reset(self):
        self._cancel()
        self._buffer = ''

    def feed(self, text):
        self._cancel()
        self._buffer += text
        # ConPTY may split escape sequences; clean only complete lines.
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            clean = ANSI.sub('', line).replace('\r', '')
            if clean or '\x1b' not in line:
                self._on_line(clean)
        if len(self._buffer) > MAX_LINE:
            self._on_line(ANSI.sub('', self._buffer[:MAX_LINE]))
            self._buffer = self._buffer[MAX_LINE:]
        if self._buffer:
            with contextlib.suppress(RuntimeError):
                self._timer = asyncio.get_running_loop().call_later(
                    PARTIAL_LINE_DELAY, self._flush_partial)

    def finish(self):
        """Hand over what is left when the program ends."""
        self._cancel()
        text, self._buffer = self._buffer, ''
        clean = ANSI.sub('', PARTIAL_ESCAPE.sub('', text)).replace('\r', '')
        if clean:
            self._on_partial(clean)

    def _cancel(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _flush_partial(self):
        self._timer = None
        text, self._buffer = self._buffer, ''
        clean = ANSI.sub('', PARTIAL_ESCAPE.sub('', text)).replace('\r', '')
        if clean.strip():
            self._on_partial(clean)
