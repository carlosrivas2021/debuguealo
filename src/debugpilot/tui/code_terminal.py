"""Code-owned lifecycle using the existing terminal renderer and input mapping."""

from debugpilot.terminal.code_session import CodeSession
from debugpilot.tui.terminal_view import TerminalContext, TerminalPane


class CodeTerminal(TerminalPane):
    def __init__(self, on_finished, **kwargs):
        super().__init__(**kwargs)
        self._on_finished = on_finished
        self._profile = None

    async def open_profile(self, profile):
        self._profile = profile
        await self._open(TerminalContext("code", profile.root))

    def _make_session(self, **callbacks):
        return CodeSession(**callbacks)

    async def _start_session(self, context):
        await self._session.open_command(
            self._profile.command, context.cwd, *self._screen_size()
        )

    def _accept_exit(self, generation):
        session = self._session
        if generation == self._generation and session is not None:
            super()._accept_exit(generation)
            self._on_finished(session.exit_code, session.error)
