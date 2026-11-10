"""Per-profile Code process ownership with the existing terminal renderer."""

import asyncio

import pyte

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.code_projects import profile_environment
from debugpilot.terminal.code_session import CodeSession
from debugpilot.tui.code_run_context import CodeRunContext
from debugpilot.tui.terminal_view import (
    MAX_FEED_CHARS,
    TerminalContext,
    TerminalPane,
    resize_screen,
)

IDLE_TITLE = "Terminal · click to type · O hide/show"
RUNNING_TITLE = "Terminal · ● running · s stop · click to type"
TYPING_TITLE = "Terminal · typing — Esc to leave"


class CodeTerminal(TerminalPane):
    """Code run output. Focus is never taken automatically so profile navigation keeps
    its arrows; the border title tells whether the terminal is receiving keys."""

    def __init__(self, on_state, **kwargs):
        super().__init__(**kwargs)
        self.border_title = IDLE_TITLE
        self._on_state = on_state
        self.contexts: dict[str, CodeRunContext] = {}
        self.selected_key: str | None = None

    @property
    def selected_context(self):
        return self.contexts.get(self.selected_key)

    @property
    def active(self) -> bool:
        context = self.selected_context
        return bool(context and context.active)

    def prepare_profile(self, profile):
        context = self.contexts.get(profile.name)
        if context is not None and (context.pending or context.active or context.stopping):
            self.select_profile(profile)
            return context, False
        rows, columns = self._screen_size()
        screen = pyte.Screen(columns=columns, lines=rows)
        context = CodeRunContext(
            key=profile.name,
            profile=profile,
            screen=screen,
            stream=pyte.Stream(screen),
            state=f"Starting: {profile.name}",
            pending=True,
        )
        self.contexts[profile.name] = context
        self.selected_key = profile.name
        self._bind_context(context)
        self.display = True
        self._report(context, context.state)
        return context, True

    def select_profile(self, profile):
        key = profile.name if profile is not None else None
        context = self.contexts.get(key) if key is not None else None
        self.selected_key = key if context is not None else None
        self.display = context is not None
        if context is None:
            self._session = None
            self._session_closed = True
            self._terminal_context = None
            rows, columns = self._screen_size()
            self._screen = pyte.Screen(columns=columns, lines=rows)
            self._stream = pyte.Stream(self._screen)
            self._update_title()
            self.refresh()
            return None
        self._bind_context(context)
        self._update_title()
        self.refresh()
        return context

    def _bind_context(self, context):
        self._session = context.session
        self._session_closed = not context.active
        self._terminal_context = TerminalContext("code", context.profile.root)
        self._screen = context.screen
        self._stream = context.stream
        if not self.size.height:
            # Hidden: a fallback size would shrink later and pyte drops lines from the top.
            return
        rows, columns = self._screen_size()
        resize_screen(context.screen, rows, columns)
        if context.active and context.session is not None:
            context.session.resize(rows, columns)

    def _report(self, context, message):
        context.state = message
        if self.selected_context is context:
            self._on_state(context.profile, message)
        self._update_title()

    def _update_title(self, focused=None):
        """Say whether the selected program runs, takes keys, or how it ended."""
        # Focus events fire before has_focus changes, so they pass the new state.
        focused = self.has_focus if focused is None else focused
        context = self.selected_context
        if context is not None and (context.pending or context.active):
            self.border_title = TYPING_TITLE if focused else RUNNING_TITLE
        elif context is not None and context.ended:
            self.border_title = f"Terminal · {context.ended}"
        else:
            self.border_title = IDLE_TITLE

    def _finish(self, context, ended, marker):
        """Close the transcript with a visible marker and no cursor waiting for input."""
        context.ended = ended
        separator = "\r\n" if context.screen.cursor.x else ""
        context.stream.feed(f"{separator}── {marker} ──\r\n\x1b[?25l")
        if self.selected_context is context:
            self.refresh()
        self._update_title()

    async def start_context(self, context):
        if context.start_task is not asyncio.current_task():
            return
        generation = context.generation
        loop = asyncio.get_running_loop()
        session = CodeSession(
            on_output=lambda text: loop.call_soon_threadsafe(
                self._accept_context_output, context, generation, text
            ),
            on_exit=lambda: loop.call_soon_threadsafe(
                self._accept_context_exit, context, generation
            ),
        )
        context.session = session
        if self.selected_context is context:
            self._bind_context(context)
        try:
            rows, columns = self._screen_size()
            # envFile is read now, so a missing or invalid file stops the run here.
            environment = profile_environment(context.profile)
            await session.open_command(
                context.profile.command, context.profile.root, rows, columns, environment
            )
            if context.generation == generation and not context.stopping:
                if context.state.startswith("Exited:"):
                    context.pending = False
                    context.active = False
                else:
                    context.pending = False
                    context.active = True
                    self._report(
                        context, f"Running: {context.profile.name} · {context.profile.root}"
                    )
                if self.selected_context is context:
                    self._bind_context(context)
        except asyncio.CancelledError:
            if not session._closed:
                await session.close_session()
            raise
        except (OSError, RuntimeError, ConfigurationError) as error:
            if context.generation == generation and not context.stopping:
                context.pending = False
                context.active = False
                self._report(context, f"Unable to run {context.profile.name}: {error}")
                if self.selected_context is context:
                    self._session_closed = True
                    self.refresh()

    def _accept_context_output(self, context, generation, text):
        if context.generation != generation or context.stopping:
            return
        context.stream.feed(text[:MAX_FEED_CHARS])
        if self.selected_context is context:
            self._screen = context.screen
            self._stream = context.stream
            self.refresh()

    def _accept_context_exit(self, context, generation):
        if context.generation != generation or context.stopping:
            return
        context.pending = False
        context.active = False
        session = context.session
        message = session.error or f"Exited: {session.exit_code}"
        ended = f"exited {session.exit_code}" if not session.error else "ended with an error"
        self._finish(context, ended, message)
        self._report(context, message)
        if self.selected_context is context:
            self._session_closed = True
            self.refresh()

    async def stop_selected(self):
        context = self.selected_context
        if context is None or not (context.pending or context.active or context.stopping):
            return
        await self.close_context(context)

    async def close_context(self, context):
        current = asyncio.current_task()
        if context.close_task is not None:
            if context.close_task is not current:
                await asyncio.shield(context.close_task)
            return
        context.stopping = True
        context.close_task = asyncio.create_task(
            self._close_context_owned(context, current)
        )
        await asyncio.shield(context.close_task)

    async def _close_context_owned(self, context, initiator):
        current = asyncio.current_task()
        context.generation += 1
        context.pending = False
        context.active = False
        try:
            task = context.start_task
            if task is not None and task not in {current, initiator} and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            session = context.session
            if session is not None:
                await session.close_session()
            self._finish(context, "stopped", "Stopped")
            self._report(context, "Stopped")
            if self.selected_context is context:
                self._bind_context(context)
                self._session_closed = True
                self.refresh()
        except (TimeoutError, OSError) as error:
            # The session kept its owner handle: stay live so Stop can retry it and
            # a new start cannot replace it, and let other profiles keep closing.
            context.active = True
            self._report(context, f"Stop incomplete: {error} Press Stop to retry.")
        finally:
            context.stopping = False
            context.close_task = None

    async def close_all(self):
        for context in list(self.contexts.values()):
            await self.close_context(context)

    async def close_session(self):
        await self.close_all()

    def on_focus(self) -> None:
        self._update_title(focused=True)

    def on_blur(self) -> None:
        self._update_title(focused=False)
