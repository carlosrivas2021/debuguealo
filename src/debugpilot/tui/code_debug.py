"""Code-only debug presentation and generation-scoped asynchronous ownership."""

import asyncio
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, RichLog, Static

from debugpilot.debugger import (
    DebugError,
    GoAttachSession,
    GoDebugSession,
    NodeDebugSession,
    PythonDebugSession,
)
from debugpilot.storage.code_projects import is_node_command, is_npm_command


class CodeDebug(Vertical):
    def __init__(self, browser, state_changed, finished):
        super().__init__(id='code-debug')
        self.browser = browser
        self.state_changed = state_changed
        self.finished = finished
        self.session = None
        self.profile = None
        self.active = False
        self._generation = 0
        self._pause = 0
        self._tasks = set()
        self._start_task = None
        self._frames = []
        self._update_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        with Horizontal(id='code-debug-controls'):
            yield Button('Continue', id='code-continue', disabled=True)
            yield Button('Over F10', id='code-over', disabled=True)
            yield Button('In F11', id='code-in', disabled=True)
            yield Button('Out Shift+F11', id='code-out', disabled=True)
        with Horizontal(id='code-inspection'):
            yield DataTable(id='code-stack', cursor_type='row')
            yield Static('Variables: —', id='code-variables', markup=False)
        yield RichLog(id='code-debug-output', max_lines=2000, markup=False, wrap=True)

    def on_mount(self):
        self.query_one(DataTable).add_columns('Frame', 'Source', 'Line')
        self.display = False

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _current(self, generation):
        return self.active and self._generation == generation

    def start(self, profile):
        if self.active:
            return
        self._generation += 1
        generation = self._generation
        self.active = True
        self.profile = profile  # Frozen CodeProject, never the current table selection.
        self.display = True
        self.query_one(RichLog).clear()
        self._invalidate()

        def event(message):
            # Backend enqueues before calling the hook, including during start().
            # Drain even obsolete sessions without retaining an event history.
            while not session.events.empty():
                session.events.get_nowait()
            if self._current(generation):
                self.call_later(self._event, generation, message)

        def output(category, text):
            if self._current(generation):
                self.query_one(RichLog).write(f'[{profile.name} · {category}] {text.rstrip()}')

        command_name = Path(profile.command[0]).name.lower() if profile.command else ""
        backend = (
            GoAttachSession
            if profile.go_attach is not None
            else GoDebugSession
            if command_name in {"go", "go.exe"}
            else NodeDebugSession
            if is_node_command(profile.command)
            or (is_npm_command(profile.command) and profile.node_debug is not None)
            else PythonDebugSession
        )
        session = self.session = backend(on_event=event, on_output=output)
        intent = self.browser.breakpoint_snapshot(profile.root)
        self.state_changed(f'Starting debug: {profile.name} · {profile.root}')
        self._start_task = self._spawn(self._start(session, generation, intent))

    async def _start(self, session, generation, intent):
        try:
            await session.start(self.profile, intent)
            if self._current(generation):
                self._verification()
        except (DebugError, OSError) as error:
            if self._current(generation):
                await self.close()
                message = f'Unable to debug {self.profile.name}: {error}'
                self.state_changed(message)
                self.app.notify(message, severity='warning')
                self.finished()

    def _verification(self):
        self.browser.set_verification(
            self.profile.root, self.session.verified_breakpoints,
            self.session.requested_breakpoints,
        )

    def _invalidate(self):
        self._pause += 1
        self._frames = []
        if not self.query(DataTable):
            return  # Children are already pruned during repeated unmount cleanup.
        self.query_one(DataTable).clear()
        self.query_one('#code-variables', Static).update('Variables: —')
        self.browser.clear_execution()
        for button in self.query(Button):
            button.disabled = True

    def _event(self, generation, message):
        if not self._current(generation):
            return
        name, body = message.get('event'), message.get('body', {})
        if name == 'state':
            state = body.get('state')
            if state != 'stopped':
                self._invalidate()
            if self.profile.go_attach is not None:
                label = {
                    'starting': 'Connecting', 'running': 'Attached',
                    'stopped': 'Stopped', 'closed': 'Disconnected',
                }.get(state, f'Debug {state}')
            else:
                label = f'Debug {state}'
            self.state_changed(f'{label}: {self.profile.name} · {self.profile.root}')
            if state == 'closed':
                self.active = False
                self.browser.set_verification(self.profile.root, {})
                if self.profile.go_attach is None:
                    result = (
                        "finalizado; código de salida no disponible"
                        if self.session.exit_code is None
                        and Path(self.profile.command[0]).name.lower() in {"go", "go.exe"}
                        else f"Exited: {self.session.exit_code}"
                    )
                    self.state_changed(
                        f'{result} · {self.profile.name} · {self.profile.root}'
                    )
                else:
                    self.state_changed(
                        f'Disconnected: {self.profile.name} · {self.profile.root} · '
                        'target remains managed by Containers'
                    )
                self.finished()
        elif name == 'stopped':
            self._invalidate()
            for button in self.query(Button):
                button.disabled = False
            self._spawn(self._inspect(generation, self._pause))
        elif name in {'breakpoint', 'breakpoints'}:
            self._verification()

    def _paused(self, generation, pause):
        return (self._current(generation) and pause == self._pause
                and self.session.state == 'stopped')

    async def _inspect(self, generation, pause):
        try:
            session = self.session
            frames = await session.stack()
            if not self._paused(generation, pause):
                return
            self._frames = frames
            table = self.query_one(DataTable)
            table.clear()
            for index, frame in enumerate(frames):
                table.add_row(frame.get('name', '?'), frame.get('source', {}).get('path', '?'),
                              str(frame.get('line', '?')), key=str(index))
            if frames:
                await self._frame(generation, pause, frames[0])
        except DebugError as error:
            if self._paused(generation, pause):
                self.app.notify(str(error), severity='warning')

    async def _frame(self, generation, pause, frame):
        session = self.session
        scopes = await session.scopes(frame['id'])
        values = []
        for scope in scopes:
            if not self._paused(generation, pause):
                return
            if scope.get('expensive'):
                continue
            variables = await session.variables(scope['variablesReference'])
            values.append(scope.get('name', 'Scope') + ':')
            values.extend(f"{v['name']} = {v.get('value', '')}" for v in variables)
        if not self._paused(generation, pause):
            return
        self.query_one('#code-variables', Static).update('\n'.join(values) or 'Variables: —')
        path = frame.get('source', {}).get('path')
        if path:
            self.browser.show_execution(self.profile.root, Path(path), frame.get('line', 1))

    @on(DataTable.RowSelected, '#code-stack')
    def select_frame(self, event):
        if self.active and self.session.state == 'stopped':
            self._pause += 1
            self.query_one('#code-variables', Static).update('Variables: —')
            self.browser.clear_execution()
            self._spawn(self._select_frame(self._generation, self._pause, event.row_key.value))

    async def _select_frame(self, generation, pause, key):
        try:
            await self._frame(generation, pause, self._frames[int(key)])
        except (DebugError, IndexError, ValueError) as error:
            if self._paused(generation, pause):
                self.app.notify(f'Unable to inspect frame: {error}', severity='warning')

    @on(Button.Pressed, '#code-continue, #code-over, #code-in, #code-out')
    def control(self, event):
        self.resume({'code-continue': 'continue_execution', 'code-over': 'step_over',
                     'code-in': 'step_in', 'code-out': 'step_out'}[event.button.id])

    def resume(self, command):
        if not self.active or self.session.state != 'stopped':
            return
        self._invalidate()
        self._spawn(self._resume(self._generation, command))

    async def _resume(self, generation, command):
        try:
            if self._current(generation):
                await getattr(self.session, command)()
        except DebugError as error:
            if self._current(generation):
                self.app.notify(str(error), severity='warning')

    def breakpoints_changed(self, event):
        if self.active and event.root == self.profile.root.resolve():
            self._spawn(self._update(self._generation, event.path, event.lines))

    async def _update(self, generation, path, lines):
        # Serialized replacements preserve rapid toggle ordering.
        async with self._update_lock:
            if not self._current(generation):
                return
            try:
                if self._start_task is not None and not self._start_task.done():
                    await asyncio.shield(self._start_task)
                if self._current(generation):
                    await self.session.set_breakpoints(str(path), lines)
                    if self._current(generation):
                        self._verification()
            except DebugError as error:
                if self._current(generation):
                    self.app.notify(str(error), severity='warning')

    async def close(self):
        self._generation += 1
        self.active = False
        self._invalidate()
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.session is not None:
            await self.session.close()
        if self.profile is not None:
            self.browser.set_verification(self.profile.root, {})
