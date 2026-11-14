"""Code debug contexts with one shared, selection-routed presentation."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, RichLog, Static

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.debugger import (
    DebugError,
    GoAttachSession,
    GoDebugSession,
    NodeAttachSession,
    NodeDebugSession,
    PythonAttachSession,
    PythonDebugSession,
)
from debugpilot.storage.code_projects import is_node_command, is_npm_command
from debugpilot.storage.watches import MAX_WATCHES_PER_ROOT, WatchStore, watch_expression

MAX_WATCH_VALUE = 200


def _attach_language(profile):
    if profile.go_attach is not None:
        return 'Go'
    return 'Node' if profile.node_attach is not None else 'Python'


def _frame_cells(frame):
    """Stack row cells; frames without a source file (runtime internals) are dimmed."""
    path = frame.get('source', {}).get('path')
    style = '' if path else 'bright_black'
    cells = (frame.get('name', '?'), path or '?', str(frame.get('line', '?')))
    return tuple(Text(str(cell), style=style) for cell in cells)


def _variable_value(value):
    """One line per variable: a multi-line value (like a function body) shows its first line."""
    lines = str(value).splitlines() or ['']
    text = lines[0].rstrip() + (' …' if len(lines) > 1 else '')
    return text if len(text) <= MAX_WATCH_VALUE else text[:MAX_WATCH_VALUE - 1] + '…'


def _watch_error(error):
    # A debugger may return a whole traceback; its last line names the actual error.
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    return '⚠ ' + (lines[-1] if lines else 'Evaluation failed.')


def _watch_value(value):
    value = ' '.join(str(value).split())
    return value if len(value) <= MAX_WATCH_VALUE else value[:MAX_WATCH_VALUE - 1] + '…'


class OutputLines:
    """Turns a debugged program's output chunks into debug output lines.

    print('text') can arrive as 'text' and then a lone newline (debugpy on Windows); that
    newline ends the open line rather than adding an empty one.
    """

    def __init__(self):
        self._open = {}

    def accept(self, category, text):
        """Whether this chunk becomes a line of its own."""
        joined = self._open.get(category, False) and text in {'\n', '\r\n'}
        self._open[category] = not text.endswith('\n')
        return not joined


class ProgramInput(Input):
    """One line of input for the debugged program; Ctrl+D ends its input."""

    BINDINGS = [Binding('ctrl+d', 'end_input', 'End input', show=False)]

    def __init__(self, send, end):
        super().__init__(
            placeholder='Program input · Enter sends a line · Ctrl+D ends input',
            id='code-debug-input', compact=True,
        )
        self._send = send
        self._end = end
        self.display = False

    def _on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input is self:
            event.stop()
            self._send(self.value)
            self.value = ''

    def action_end_input(self) -> None:
        self._end(self.value)
        self.value = ''


@dataclass
class DebugContext:
    profile: object
    key: tuple
    session: object = None
    active: bool = False
    generation: int = 0
    pause: int = 0
    tasks: set = field(default_factory=set)
    start_task: object = None
    frames: list = field(default_factory=list)
    output: list = field(default_factory=list)
    variables: str = 'Variables: —'
    execution: tuple | None = None
    state: str = ''
    unexpected_disconnect: bool = False
    frame_row: int = 0
    # Watch expression -> displayed value for the current pause and frame.
    watch_values: dict = field(default_factory=dict)
    watch_frame: object = None
    close_error: str | None = None
    update_lock: object = field(default_factory=asyncio.Lock)
    stopping: bool = False
    close_task: object = None


class CodeDebug(Vertical):
    """Own one debugger per frozen profile while presenting only the selected one."""

    def __init__(self, browser, state_changed, finished):
        super().__init__(id='code-debug')
        self.browser = browser
        self.state_changed = state_changed
        self.finished = finished
        self.contexts: dict[tuple, DebugContext] = {}
        self.selected_key: tuple | None = None
        # Owned here but placed by the host (at the bottom, like the run terminal).
        self.output = RichLog(id='code-debug-output', max_lines=2000, markup=False, wrap=True)
        self.output.border_title = 'Debug output'
        self.output.display = False
        self.input = ProgramInput(self._send_input, self._end_input)
        self.watch_store = WatchStore()
        try:
            self.watches: dict[Path, list[str]] = {
                root: list(expressions) for root, expressions in self.watch_store.load().items()
            }
            self._watch_error = None
        except ConfigurationError as error:
            self.watches = {}
            self._watch_error = str(error)

    @property
    def display(self):
        return Vertical.display.fget(self)

    @display.setter
    def display(self, value):
        # The output pane lives elsewhere in the DOM; keep it visible exactly with the panel.
        Vertical.display.fset(self, value)
        self.output.display = value

    @staticmethod
    def profile_key(profile):
        # The saved name is the stable identity; a live context pins its original config.
        return profile.name

    @property
    def selected(self):
        return self.contexts.get(self.selected_key)

    @property
    def session(self):
        return self.selected.session if self.selected else None

    @property
    def profile(self):
        return self.selected.profile if self.selected else None

    @property
    def active(self):
        return bool(self.selected and self.selected.active)

    @property
    def _generation(self):
        return self.selected.generation if self.selected else 0

    @property
    def _tasks(self):
        return self.selected.tasks if self.selected else set()

    @property
    def _start_task(self):
        return self.selected.start_task if self.selected else None

    def compose(self) -> ComposeResult:
        with Horizontal(id='code-debug-controls'):
            yield Button('▶ Continue', id='code-continue', disabled=True)
            yield Button('Over', id='code-over', disabled=True)
            yield Button('In', id='code-in', disabled=True)
            yield Button('Out', id='code-out', disabled=True)
        with Horizontal(id='code-inspection'):
            yield DataTable(id='code-stack', cursor_type='row')
            with Vertical(id='code-watch-pane'):
                yield Input(placeholder='+ Add watch expression', id='code-watch-input',
                            compact=True)
                yield DataTable(id='code-watches', cursor_type='row')
            yield Static('Variables: —', id='code-variables', markup=False)

    def on_mount(self):
        stack = self.query_one('#code-stack', DataTable)
        stack.add_columns('Frame', 'Source', 'Line')
        stack.border_title = 'Call stack'
        self.query_one('#code-watches', DataTable).add_columns('Expression', 'Value')
        self.query_one('#code-watch-pane').border_title = 'Watch'
        self.query_one('#code-variables', Static).border_title = 'Variables'
        self.display = False
        if self._watch_error:
            self.app.notify(self._watch_error, severity='warning')

    def _spawn(self, context, coroutine):
        task = asyncio.create_task(coroutine)
        context.tasks.add(task)
        task.add_done_callback(context.tasks.discard)
        return task

    def _current(self, context, generation):
        return context.active and context.generation == generation

    def context_for(self, profile):
        if profile is None:
            return None
        return self.contexts.get(self.profile_key(profile))

    def select_context(self, context):
        self.selected_key = context.key if context in self.contexts.values() else None
        self._show_selected()

    def select_profile(self, profile):
        context = self.context_for(profile)
        self.selected_key = context.key if context is not None else None
        if context is None and profile is not None:
            self.browser.set_verification(profile.root, {})
        self._show_selected()

    def _show_selected(self):
        context = self.selected
        self.display = context is not None
        self.sync_input()
        if context is None:
            self._clear_view()
            return
        self._render_context(context)

    def _clear_view(self):
        if not self.query(DataTable):
            return
        self.query_one('#code-stack', DataTable).clear()
        self.query_one('#code-watches', DataTable).clear()
        self.query_one('#code-variables', Static).update('Variables: —')
        self.output.clear()
        self.browser.clear_execution()
        for button in self.query(Button):
            button.disabled = True

    def _render_context(self, context):
        if self.selected is not context or not self.query(DataTable):
            return
        log = self.output
        log.clear()
        for line in context.output:
            log.write(line)
        self._render_pause(context)

    def _render_pause(self, context):
        """Rebuild the stack for a new pause; output keeps its lines and scroll."""
        if self.selected is not context or not self.query(DataTable):
            return
        table = self.query_one('#code-stack', DataTable)
        table.clear()
        for index, frame in enumerate(context.frames):
            table.add_row(*_frame_cells(frame), key=str(index))
        if context.frame_row < table.row_count:
            table.move_cursor(row=context.frame_row)
        self._render_inspection(context)

    def _render_inspection(self, context):
        """Refresh variables, controls and marker; the stack keeps its cursor."""
        if self.selected is not context or not self.query(DataTable):
            return
        self.query_one('#code-variables', Static).update(context.variables)
        self._render_watches(context)
        enabled = (
            context.active and context.session is not None
            and context.session.state == 'stopped'
        )
        for button in self.query(Button):
            button.disabled = not enabled
        self.browser.clear_execution()
        if context.session is not None and context.profile is not None:
            self._verification(context)
        if context.execution is not None:
            root, path, line = context.execution
            self.browser.show_execution(root, path, line)

    def _watches(self, context):
        return self.watches.get(Path(context.profile.root).resolve(), [])

    def _render_watches(self, context):
        if self.selected is not context or not self.query('#code-watches'):
            return
        table = self.query_one('#code-watches', DataTable)
        row = table.cursor_row
        table.clear()
        paused = context.session is not None and context.session.state == 'stopped'
        for expression in self._watches(context):
            value = context.watch_values.get(expression, '—') if paused else '—'
            table.add_row(expression, value)
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))

    async def _evaluate_watches(self, context, generation, pause, frame_id):
        values = {}
        for expression in list(self._watches(context)):
            if not self._paused(context, generation, pause):
                return
            try:
                values[expression] = _watch_value(
                    await context.session.evaluate(expression, frame_id))
            except DebugError as error:
                # One failing watch never stops the others.
                values[expression] = _watch_error(error)
        if self._paused(context, generation, pause):
            context.watch_values = values

    async def _refresh_watches(self, context, generation, pause):
        await self._evaluate_watches(context, generation, pause, context.watch_frame)
        if self._paused(context, generation, pause):
            self._render_watches(context)

    def _save_watches(self):
        try:
            self.watch_store.save(self.watches)
        except ConfigurationError as error:
            self.app.notify(str(error), severity='warning')

    @on(Input.Submitted, '#code-watch-input')
    def add_watch(self, event):
        event.input.value = ''
        context = self.selected
        if context is None:
            return
        try:
            expression = watch_expression(event.value)
        except ValueError as error:
            self.app.notify(str(error), severity='warning')
            return
        watches = self.watches.setdefault(Path(context.profile.root).resolve(), [])
        if expression in watches:
            return
        if len(watches) >= MAX_WATCHES_PER_ROOT:
            self.app.notify('A project can keep at most 100 watch expressions.',
                            severity='warning')
            return
        watches.append(expression)
        self._save_watches()
        self._render_watches(context)
        if (context.active and context.session is not None
                and context.session.state == 'stopped' and context.watch_frame is not None):
            self._spawn(context, self._refresh_watches(
                context, context.generation, context.pause))

    def on_key(self, event):
        table = self.query('#code-watches')
        if event.key != 'delete' or not table or self.app.focused is not table.first():
            return
        event.stop()
        context = self.selected
        watches = self._watches(context) if context is not None else []
        row = table.first().cursor_row
        if 0 <= row < len(watches):
            watches.pop(row)
            context.watch_values.pop(str(table.first().get_row_at(row)[0]), None)
            self._save_watches()
            self._render_watches(context)

    def _set_state(self, context, message):
        context.state = message
        if self.selected is context:
            self.state_changed(message)
        self.sync_input()

    def _input_session(self):
        context = self.selected
        session = context.session if context is not None else None
        if (context is None or not context.active or session is None
                or not getattr(session, 'supports_input', False)
                or session.state not in {'running', 'stopped'}):
            return None, None
        return context, session

    def sync_input(self):
        """Offer program input only beside a shown, live session that Code launched."""
        self.input.display = bool(self.output.display and self._input_session()[1])

    def _send_input(self, text):
        context, session = self._input_session()
        if session is None:
            return
        try:
            echo = session.input_echo()
            session.send_input(text)
        except DebugError as error:
            self.app.notify(str(error), severity='warning')
            return
        if echo:
            # Only while the program echoes, as a terminal would; getpass stays hidden.
            self._append_output(context, f'[{context.profile.name} · input] {text}')

    def _end_input(self, text):
        context, session = self._input_session()
        if session is None:
            return
        if text:
            self._send_input(text)
        try:
            session.send_eof()
        except DebugError as error:
            self.app.notify(str(error), severity='warning')

    def _deliver_output(self, context, generation, message):
        if self._current(context, generation):
            self._append_output(context, message)

    def _append_output(self, context, message):
        context.output.append(message)
        context.output = context.output[-2000:]
        if self.selected is context and self.output.is_mounted:
            self.output.write(message)

    def start(self, profile):
        key = self.profile_key(profile)
        existing = self.contexts.get(key)
        if existing is not None and existing.active:
            self.select_profile(profile)
            return
        if profile.attach is not None:
            endpoint = (profile.attach.host, profile.attach.port)
            if any(context.active and context.profile.attach is not None
                   and (context.profile.attach.host, context.profile.attach.port) == endpoint
                   for context in self.contexts.values()):
                self.state_changed(
                    f'{_attach_language(profile)} attach endpoint {endpoint[0]}:{endpoint[1]} '
                    'is already active.'
                )
                self.finished(False)
                return
        other_active = [context for context in self.contexts.values()
                        if (context.active or context.stopping) and context.key != key]
        if profile.attach is not None and any(
            context.profile.attach is not None
            and (context.profile.attach.host, context.profile.attach.port)
            == (profile.attach.host, profile.attach.port)
            for context in other_active
        ):
            self.state_changed(
                f'{_attach_language(profile)} attach endpoint '
                f'{profile.attach.host}:{profile.attach.port} '
                'is already active.'
            )
            self.finished(False)
            return
        context = existing or DebugContext(profile=profile, key=key)
        if existing is not None and (existing.active or existing.stopping):
            self.select_context(existing)
            return
        previous_session = context.session if existing is not None else None
        context.profile = profile
        self.contexts[key] = context
        self.selected_key = key
        context.generation += 1
        generation = context.generation
        context.active = True
        context.unexpected_disconnect = False
        context.output.clear()
        context.frames.clear()
        context.variables = 'Variables: —'
        context.execution = None
        self.display = True
        self._render_context(context)
        intent = self.browser.breakpoint_snapshot(profile.root)
        options = self.browser.options_snapshot(profile.root)
        self._set_state(context, f'Starting debug: {profile.name} · {profile.root}')
        context.start_task = self._spawn(
            context,
            self._launch(context, profile, generation, intent, options, previous_session),
        )

    async def _launch(self, context, profile, generation, intent, options, previous_session):
        try:
            if previous_session is not None:
                await previous_session.close()
            if not self._current(context, generation):
                return

            session = None

            def event(message):
                while not session.events.empty():
                    session.events.get_nowait()
                if self._current(context, generation):
                    self.call_later(self._event, context, generation, message)

            lines = OutputLines()

            def output(category, text):
                if lines.accept(category, text) and self._current(context, generation):
                    self.call_later(
                        self._deliver_output, context, generation,
                        f'[{profile.name} · {category}] {text.rstrip()}',
                    )

            command_name = Path(profile.command[0]).name.lower() if profile.command else ""
            backend = (
                GoAttachSession
                if profile.go_attach is not None
                else PythonAttachSession
                if profile.python_attach is not None
                else NodeAttachSession
                if profile.node_attach is not None
                else GoDebugSession
                if command_name in {"go", "go.exe"}
                else NodeDebugSession
                if is_node_command(profile.command)
                or (is_npm_command(profile.command) and profile.node_debug is not None)
                else PythonDebugSession
            )
            session = context.session = backend(on_event=event, on_output=output)
            await self._start(context, session, generation, intent, options)
        except (DebugError, OSError) as error:
            if self._current(context, generation):
                context.active = False
                message = f'Unable to debug {context.profile.name}: {error}'
                self._set_state(context, message)
                self.app.notify(message, severity='warning')
                if self.selected is context:
                    self.finished(False)

    async def _start(self, context, session, generation, intent, options=None):
        try:
            # Without options the call keeps its previous shape for every session type.
            await session.start(context.profile, intent, *((options,) if options else ()))
            if self._current(context, generation) and self.selected is context:
                self._verification(context)
        except (DebugError, OSError) as error:
            if self._current(context, generation):
                await self.close_context(context)
                message = f'Unable to debug {context.profile.name}: {error}'
                self._set_state(context, message)
                self.app.notify(message, severity='warning')
                if self.selected is context:
                    self.finished(False)

    def _verification(self, context):
        self.browser.set_verification(
            context.profile.root, context.session.verified_breakpoints,
            context.session.requested_breakpoints,
        )

    def _invalidate(self, context):
        context.pause += 1
        context.frames = []
        context.variables = 'Variables: —'
        context.execution = None
        context.frame_row = 0
        context.watch_values = {}
        context.watch_frame = None
        self._render_pause(context)

    def _event(self, context, generation, message):
        if not self._current(context, generation):
            return
        name, body = message.get('event'), message.get('body', {})
        if name == 'transportClosed' and context.profile.attach is not None:
            context.unexpected_disconnect = True
            reason = body.get('message')
            detail = f': {reason}' if reason else ''
            self._set_state(context,
                f'Unexpected disconnect; target state UNKNOWN{detail} · '
                f'{context.profile.name} · {context.profile.root}')
        elif name == 'state':
            state = body.get('state')
            if state != 'stopped':
                self._invalidate(context)
            if context.profile.attach is not None:
                label = {'starting': 'Connecting', 'running': 'Attached',
                         'stopped': 'Stopped', 'closed': 'Disconnected'}.get(
                             state, f'Debug {state}')
            else:
                label = f'Debug {state}'
            self._set_state(context, f'{label}: {context.profile.name} · {context.profile.root}')
            if state == 'closed':
                context.active = False
                if self.selected is context:
                    self.browser.set_verification(context.profile.root, {})
                if context.profile.attach is None:
                    result = (
                        "finalizado; código de salida no disponible"
                        if context.session.exit_code is None
                        and Path(context.profile.command[0]).name.lower() in {"go", "go.exe"}
                        else f"Exited: {context.session.exit_code}"
                    )
                    self._set_state(context,
                        f'{result} · {context.profile.name} · {context.profile.root}')
                else:
                    warning = getattr(context.session, 'disconnect_warning', None)
                    if context.unexpected_disconnect:
                        detail = f': {warning}' if warning else ''
                        self._set_state(context,
                            f'Unexpected disconnect; target state UNKNOWN{detail} · '
                            f'{context.profile.name} · {context.profile.root}')
                    elif warning:
                        message = f'Disconnected; target state UNKNOWN: {warning}'
                        self._set_state(context, message)
                        self.app.notify(message, severity='warning')
                    else:
                        self._set_state(context,
                            f'Disconnected: {context.profile.name} · {context.profile.root} · '
                            'target remains managed by Containers')
                if self.selected is context:
                    self._render_pause(context)
                    self.finished(context.unexpected_disconnect)
        elif name == 'stopped':
            context.pause += 1
            # Controls never wait for inspection, which may be slow or fail.
            self._render_inspection(context)
            self._spawn(context, self._inspect(context, generation, context.pause))
        elif name in {'breakpoint', 'breakpoints'}:
            if self.selected is context:
                self._verification(context)

    def _paused(self, context, generation, pause):
        return (self._current(context, generation) and pause == context.pause
                and context.session.state == 'stopped')

    async def _inspect(self, context, generation, pause):
        try:
            frames = await context.session.stack()
            if not self._paused(context, generation, pause):
                return
            context.frames = frames
            context.frame_row = 0
            self._render_pause(context)
            if frames:
                await self._frame(context, generation, pause, frames[0])
        except DebugError as error:
            if self._paused(context, generation, pause):
                self.app.notify(str(error), severity='warning')

    async def _frame(self, context, generation, pause, frame):
        scopes = await context.session.scopes(frame['id'])
        values = []
        for scope in scopes:
            if not self._paused(context, generation, pause):
                return
            if scope.get('expensive'):
                continue
            variables = await context.session.variables(scope['variablesReference'])
            values.append(scope.get('name', 'Scope') + ':')
            values.extend(
                f"{value['name']} = {_variable_value(value.get('value', ''))}"
                for value in variables
            )
        if not self._paused(context, generation, pause):
            return
        context.watch_frame = frame['id']
        await self._evaluate_watches(context, generation, pause, frame['id'])
        if not self._paused(context, generation, pause):
            return
        context.variables = '\n'.join(values) or 'Variables: —'
        path = frame.get('source', {}).get('path')
        context.execution = (
            (context.profile.root, Path(path), frame.get('line', 1)) if path else None
        )
        self._render_inspection(context)

    @on(DataTable.RowSelected, '#code-stack')
    def select_frame(self, event):
        context = self.selected
        if context is not None and context.active and context.session.state == 'stopped':
            context.pause += 1
            context.variables = 'Variables: —'
            context.execution = None
            context.watch_values = {}
            context.frame_row = event.cursor_row
            self._render_inspection(context)
            self._spawn(context, self._select_frame(
                context, context.generation, context.pause, event.row_key.value
            ))

    async def _select_frame(self, context, generation, pause, key):
        try:
            await self._frame(context, generation, pause, context.frames[int(key)])
        except (DebugError, IndexError, ValueError) as error:
            if self._paused(context, generation, pause):
                self.app.notify(f'Unable to inspect frame: {error}', severity='warning')

    @on(Button.Pressed, '#code-continue, #code-over, #code-in, #code-out')
    def control(self, event):
        self.resume({'code-continue': 'continue_execution', 'code-over': 'step_over',
                     'code-in': 'step_in', 'code-out': 'step_out'}[event.button.id])

    def resume(self, command):
        context = self.selected
        if (
            context is None or not context.active or context.session is None
            or context.session.state != 'stopped'
        ):
            return
        self._invalidate(context)
        self._spawn(context, self._resume(context, context.generation, command))

    async def _resume(self, context, generation, command):
        try:
            if self._current(context, generation):
                await getattr(context.session, command)()
        except DebugError as error:
            if self._current(context, generation):
                self.app.notify(str(error), severity='warning')

    def breakpoints_changed(self, event):
        for context in self.contexts.values():
            if context.active and event.root == context.profile.root.resolve():
                self._spawn(context, self._update(
                    context, context.generation, event.path, event.lines, event.options
                ))

    async def _update(self, context, generation, path, lines, options=None):
        async with context.update_lock:
            if not self._current(context, generation):
                return
            try:
                if context.start_task is not None and not context.start_task.done():
                    await asyncio.shield(context.start_task)
                if self._current(context, generation):
                    await context.session.set_breakpoints(
                        str(path), lines, *((options,) if options else ()))
                    if self._current(context, generation) and self.selected is context:
                        self._verification(context)
            except DebugError as error:
                if self._current(context, generation):
                    self.app.notify(str(error), severity='warning')

    async def close_context(self, context):
        if context.close_task is None:
            context.stopping = True
            context.generation += 1
            context.active = False
            self._invalidate(context)
            initiator = asyncio.current_task()
            context.close_task = asyncio.create_task(
                self._close_context_owned(context, initiator)
            )
        await asyncio.shield(context.close_task)
        return getattr(context.session, 'disconnect_warning', None)

    async def _close_context_owned(self, context, initiator):
        current = asyncio.current_task()
        try:
            tasks = [task for task in context.tasks if task not in {current, initiator}]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            session = context.session
            context.close_error = None
            if session is not None:
                try:
                    await session.close()
                except (TimeoutError, OSError) as error:
                    # The session kept its owner handle: stay live so Stop can retry it
                    # and a new start cannot replace it.
                    context.close_error = str(error)
                    context.active = True
                    return None
            warning = getattr(session, 'disconnect_warning', None)
            if (
                warning and context.profile is not None
                and self.selected is context and self.output.is_mounted
            ):
                self._append_output(
                    context, f'[{context.profile.name} · stderr] Warning: {warning}'
                )
            if context.profile is not None and self.selected is context:
                self.browser.set_verification(context.profile.root, {})
            context.unexpected_disconnect = False
            return warning
        finally:
            context.stopping = False
            context.close_task = None

    async def close(self):
        context = self.selected
        return await self.close_context(context) if context is not None else None

    async def close_all(self):
        warnings = []
        for context in list(self.contexts.values()):
            warnings.append(await self.close_context(context))
        return warnings
