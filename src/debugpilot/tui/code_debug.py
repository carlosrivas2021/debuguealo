"""Code debug contexts with one shared, selection-routed presentation."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from rich.cells import cell_len
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
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
from debugpilot.storage.exception_modes import (
    DEFAULT_EXCEPTION_MODE,
    EXCEPTION_MODES,
    ExceptionModeStore,
)
from debugpilot.storage.watches import MAX_WATCHES_PER_ROOT, WatchStore, watch_expression
from debugpilot.tui.theme import theme_style

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


def _own_frame(frames, root):
    """The first frame whose source is inside the project, or the top frame when none is."""
    root = Path(root).resolve()
    for index, frame in enumerate(frames):
        path = frame.get('source', {}).get('path')
        try:
            if path and Path(path).resolve().is_relative_to(root):
                return index
        except (OSError, ValueError, RuntimeError):
            continue
    return 0


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


# Nested variables open at most this many levels deep (cyclic objects never end).
MAX_VARIABLE_DEPTH = 8


@dataclass(frozen=True)
class VariableRow:
    """A scope heading (name None) or one variable of the paused frame.

    reference is the scope or object that holds the variable (what a change is sent to);
    children is the variable's own reference when it has fields, else 0. path names the
    scope and every variable down to this one, which keeps it expanded across pauses.
    """

    scope: str
    reference: int
    name: str | None = None
    value: str = ''
    depth: int = 0
    children: int = 0
    path: tuple = ()
    expanded: bool = False
    expression: str = ''  # The adapter's evaluateName, when it gives one.

    @property
    def prefix(self):
        """Indent and expand marker before the name."""
        marker = '▾ ' if self.expanded else '▸ ' if self.children else '  '
        return '  ' * self.depth + marker

    @property
    def line(self):
        return f'{self.scope}:' if self.name is None else (
            f'{self.prefix}{self.name} = {_variable_value(self.value)}')


# A copied tree stops here, so a huge or cyclic value cannot stall the copy.
MAX_COPY_LINES = 2000


async def copy_text(session, variable, frame_id):
    """What C copies: the whole value in the program's language, or its fields as a tree."""
    full_value = getattr(session, 'full_value', None)
    if full_value is not None:
        try:
            text = await full_value(variable.expression, variable.children, frame_id)
        except DebugError:
            text = None
        if text is not None:
            return text
    if not variable.children:
        return variable.value
    lines = [f'{variable.name} = {variable.value}']
    await _copy_tree(session, variable.children, 1, lines)
    return '\n'.join(lines)


async def _copy_tree(session, reference, depth, lines):
    for value in await session.variables(reference):
        if len(lines) >= MAX_COPY_LINES:
            return
        lines.append(f"{'  ' * depth}{value['name']} = {value.get('value', '')}")
        children = value.get('variablesReference') or 0
        if children and depth < MAX_VARIABLE_DEPTH:
            await _copy_tree(session, children, depth + 1, lines)


# Watch rows' paths start with this, so they never meet a scope's variables in `expanded`.
WATCH_PATH = '#watch'


class ValueTable(DataTable):
    """Rows of values that open into their fields: Right/Left/Space expand, C copies."""

    BINDINGS = [
        Binding('right', 'expand', 'Expand', show=False),
        Binding('left', 'collapse', 'Collapse', show=False),
        Binding('space', 'toggle', 'Expand/collapse', show=False),
        Binding('c', 'copy_value', 'Copy value', show=False),
    ]

    class Toggled(Message):
        """A variable with fields was expanded or collapsed."""

        def __init__(self, table, variable, expanded):
            super().__init__()
            self.table = table
            self.variable = variable
            self.expanded = expanded

        @property
        def control(self):
            return self.table

    def __init__(self, **kwargs):
        super().__init__(cursor_type='row', **kwargs)
        self.variable_rows: tuple[VariableRow, ...] = ()

    def show(self, rows):
        rows = tuple(rows)
        if rows == self.variable_rows and self.row_count == len(rows):
            return
        row = self.cursor_row
        self.variable_rows = rows
        self.clear()
        for index, variable in enumerate(rows):
            self.add_row(*self._cells(variable), key=str(index))
        if rows:
            self.move_cursor(row=min(row, len(rows) - 1))

    def recolor(self):
        """Draw the same rows again, in the active theme's colors."""
        rows, self.variable_rows = self.variable_rows, ()
        self.show(rows)

    def _cells(self, variable):
        raise NotImplementedError

    def on_resize(self) -> None:
        # The value preview below grows and shrinks this table; keep the cursor's row in view.
        if self.variable_rows:
            # Read the row when it runs: the cursor may move before the next refresh.
            self.call_after_refresh(lambda: self.move_cursor(row=self.cursor_row))

    @property
    def highlighted(self):
        """The row under the cursor, or None."""
        if 0 <= self.cursor_row < len(self.variable_rows):
            return self.variable_rows[self.cursor_row]
        return None

    class CopyRequested(Message):
        """C on a variable: copy its whole value."""

        def __init__(self, table, variable):
            super().__init__()
            self.table = table
            self.variable = variable

        @property
        def control(self):
            return self.table

    def action_copy_value(self) -> None:
        variable = self.highlighted
        if variable is not None and variable.name is not None:
            self.post_message(self.CopyRequested(self, variable))

    def action_expand(self) -> None:
        variable = self.highlighted
        if variable is not None and variable.children and not variable.expanded:
            self.post_message(self.Toggled(self, variable, True))

    def action_toggle(self) -> None:
        """Space opens or closes a variable's fields, as it does in the file tree."""
        variable = self.highlighted
        if variable is not None and variable.children:
            self.post_message(self.Toggled(self, variable, not variable.expanded))

    def action_collapse(self) -> None:
        variable = self.highlighted
        if variable is None or variable.name is None:
            return
        if variable.expanded:
            self.post_message(self.Toggled(self, variable, False))
            return
        # On a field, go to the variable that holds it.
        parent = variable.path[:-1]
        for index in range(self.cursor_row - 1, -1, -1):
            if self.variable_rows[index].name is not None and (
                    self.variable_rows[index].path == parent):
                self.move_cursor(row=index)
                return



class VariablesTable(ValueTable):
    """The paused frame's variables: scope headings and one selectable row per variable."""

    def __init__(self, **kwargs):
        super().__init__(show_header=False, **kwargs)

    def on_mount(self):
        self.add_column('Variable')

    def _cells(self, variable):
        style = theme_style(self.app, 'text-secondary', bold=True) if variable.name is None else ''
        return (Text(variable.line, style=style, no_wrap=True),)

    @property
    def text(self):
        """What the pane shows, one line per row."""
        return '\n'.join(row.line for row in self.variable_rows) or 'Variables: —'


class WatchTable(ValueTable):
    """Watch expressions and their values; a value with fields opens like a variable."""

    def on_mount(self):
        self.add_columns('Expression', 'Value')

    def _cells(self, watch):
        # A plain watch shows its expression as typed; markers only where something opens.
        label = watch.name if watch.depth == 0 and not watch.children else (
            watch.prefix + watch.name)
        return Text(label, no_wrap=True), Text(_watch_value(watch.value), no_wrap=True)


class VariableEditor(Input):
    """Edits a variable over its own row: Enter sets the typed value, Esc cancels."""

    BINDINGS = [Binding('escape', 'cancel', 'Cancel', show=False)]

    def __init__(self, cancel):
        super().__init__(id='variable-value', compact=True, select_on_focus=False)
        self._cancel = cancel
        self.display = False

    def action_cancel(self) -> None:
        self._cancel()


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
    """One line of input for the debugged program; Ctrl+D ends its input, Esc leaves."""

    BINDINGS = [
        Binding('ctrl+d', 'end_input', 'End input', show=False),
        Binding('escape', 'leave', 'Leave', show=False),
    ]

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

    def action_leave(self) -> None:
        # Like the Code terminal's Esc: back to the profiles, where pane keys work again.
        self.screen.query_one('#code-projects').focus()
        self.value = ''


MAX_CONSOLE_HISTORY = 100


class EvaluateInput(Input):
    """The debug console: Enter evaluates a line in the selected paused frame.

    Up and Down walk the lines already run in this Debugealo session; Esc leaves.
    """

    BINDINGS = [
        Binding('up', 'older', 'Older', show=False),
        Binding('down', 'newer', 'Newer', show=False),
        Binding('escape', 'leave', 'Leave', show=False),
    ]

    def __init__(self, run):
        super().__init__(placeholder=_console_placeholder(None), id='code-debug-eval',
                         compact=True)
        self._run = run
        self.history: list[str] = []
        # The history line shown while walking it with Up/Down, or None when not walking.
        self._position = None
        self.display = False

    def _on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input is not self:
            return
        event.stop()
        text = self.value.strip()
        self.value = ''
        self._position = None
        if not text:
            return
        if not self.history or self.history[-1] != text:
            self.history.append(text)
            del self.history[:-MAX_CONSOLE_HISTORY]
        self._run(text)

    def _recall(self, position):
        self._position = position
        self.value = '' if position is None else self.history[position]
        self.cursor_position = len(self.value)

    def action_older(self) -> None:
        if self.history:
            position = len(self.history) if self._position is None else self._position
            self._recall(max(0, position - 1))

    def action_newer(self) -> None:
        if self._position is not None:
            newer = self._position + 1
            self._recall(newer if newer < len(self.history) else None)

    def action_leave(self) -> None:
        self.screen.query_one('#code-projects').focus()
        self.value = ''
        self._position = None


def _console_placeholder(frame):
    if frame is None:
        return 'Evaluate · Enter runs in the paused frame · ↑↓ history'
    path = frame.get('source', {}).get('path')
    where = Path(path).name if path else frame.get('name', '?')
    return f'Evaluate · Enter runs in {where}:{frame.get("line", "?")} · ↑↓ history'


def _with_run_to(lines, options, line):
    """The file's breakpoints plus a plain one on the Run to cursor line."""
    return (tuple(sorted({*lines, line})),
            {number: option for number, option in options.items() if number != line})


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
    variables: tuple = ()
    execution: tuple | None = None
    state: str = ''
    unexpected_disconnect: bool = False
    frame_row: int = 0
    # Each evaluated watch and the fields opened under it, for the current pause and frame.
    watch_rows: tuple = ()
    watch_frame: object = None
    # Paths (scope, variable, field, ...) the user expanded; kept across pauses.
    expanded: set = field(default_factory=set)
    close_error: str | None = None
    update_lock: object = field(default_factory=asyncio.Lock)
    stopping: bool = False
    close_task: object = None
    # (file, line) of a one-shot Run to cursor breakpoint, kept until the next pause.
    run_to: tuple | None = None


class CodeDebug(Vertical):
    """Own one debugger per frozen profile while presenting only the selected one."""

    def __init__(self, browser, state_changed, finished):
        super().__init__(id='code-debug')
        self.browser = browser
        self.state_changed = state_changed
        self.finished = finished
        self.contexts: dict[tuple, DebugContext] = {}
        self.selected_key: tuple | None = None
        # (context, generation, pause, variable) while a variable's value is edited.
        self._editing = None
        # Owned here but placed by the host (at the bottom, like the run terminal).
        self.output = RichLog(id='code-debug-output', max_lines=2000, markup=False, wrap=True)
        self.output.border_title = 'Debug output'
        self.output.display = False
        self.input = ProgramInput(self._send_input, self._end_input)
        self.console = EvaluateInput(self._evaluate_console)
        self.watch_store = WatchStore()
        try:
            self.watches: dict[Path, list[str]] = {
                root: list(expressions) for root, expressions in self.watch_store.load().items()
            }
            self._watch_error = None
        except ConfigurationError as error:
            self.watches = {}
            self._watch_error = str(error)
        self.exception_store = ExceptionModeStore()
        try:
            self.exception_modes: dict[Path, str] = self.exception_store.load()
            self._exception_error = None
        except ConfigurationError as error:
            self.exception_modes = {}
            self._exception_error = str(error)

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
                yield WatchTable(id='code-watches')
                yield Static('', id='watch-preview', markup=False)
            with Vertical(id='code-variables-pane'):
                yield VariablesTable(id='code-variables')
                yield Static('', id='variable-preview', markup=False)
                yield VariableEditor(self._close_variable_editor)

    def on_mount(self):
        stack = self.query_one('#code-stack', DataTable)
        stack.add_columns('Frame', 'Source', 'Line')
        stack.border_title = 'Call stack'
        self.query_one('#code-watch-pane').border_title = 'Watch'
        self.query_one('#code-variables', VariablesTable).border_title = 'Variables'
        self.display = False
        if self._watch_error:
            self.app.notify(self._watch_error, severity='warning')
        if self._exception_error:
            self.app.notify(self._exception_error, severity='warning')

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
        self._hide_variable_editor()
        self.query_one('#code-variables', VariablesTable).show(())
        self._show_preview()
        self.output.clear()
        self.output.border_title = 'Debug output'
        self.browser.clear_execution()
        for button in self.query(Button):
            button.disabled = True

    def recolor(self):
        """After a theme change, draw again the rows that carry theme colors."""
        for table in self.query(ValueTable):
            table.recolor()

    def _render_context(self, context):
        if self.selected is not context or not self.query(DataTable):
            return
        log = self.output
        log.clear()
        log.border_title = self._output_title(context)
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
        # Its row may no longer hold the same variable; the keys go back to the table.
        table, refocus = self._hide_variable_editor()
        if refocus:
            table.focus()
        self.query_one('#code-variables', VariablesTable).show(context.variables)
        self._show_preview()
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
        self.sync_console()

    def _watches(self, context):
        return self.watches.get(Path(context.profile.root).resolve(), [])

    def _render_watches(self, context):
        if self.selected is not context or not self.query('#code-watches'):
            return
        paused = context.session is not None and context.session.state == 'stopped'
        evaluated = {}
        for watch in context.watch_rows if paused else ():
            if watch.depth == 0:
                evaluated[watch.name] = []
            evaluated[watch.path[1]].append(watch)
        rows = []
        for expression in self._watches(context):
            # A watch added since the last evaluation waits for the next one.
            rows.extend(evaluated.get(expression) or (
                VariableRow(WATCH_PATH, 0, expression, '—', path=(WATCH_PATH, expression)),))
        self.query_one('#code-watches', WatchTable).show(rows)
        self._show_preview()

    async def _evaluate_watches(self, context, generation, pause, frame_id):
        rows = []
        for expression in list(self._watches(context)):
            if not self._paused(context, generation, pause):
                return
            try:
                result = await self._inspect_watch(context.session, expression, frame_id)
            except DebugError as error:
                # One failing watch never stops the others.
                result = {'value': _watch_error(error), 'variablesReference': 0}
            children = result.get('variablesReference') or 0
            path = (WATCH_PATH, expression)
            watch = VariableRow(WATCH_PATH, 0, expression, str(result.get('value', '')), 0,
                                children, path, bool(children) and path in context.expanded,
                                expression)
            rows.append(watch)
            if watch.expanded and not await self._variables(
                    context, generation, pause, rows, watch):
                return
        if self._paused(context, generation, pause):
            context.watch_rows = tuple(rows)

    @staticmethod
    async def _inspect_watch(session, expression, frame_id):
        inspect = getattr(session, 'inspect', None)
        if inspect is None:
            return {'value': await session.evaluate(expression, frame_id)}
        return await inspect(expression, frame_id)

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
        watch = table.first().highlighted
        # A field opened under a watch is not a watch of its own.
        if watch is not None and watch.depth == 0 and watch.name in watches:
            watches.remove(watch.name)
            context.watch_rows = tuple(row for row in context.watch_rows
                                       if row.path[1] != watch.name)
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
        """One line under the output: Program input while running, the console while paused.

        Program input is offered only for a live session that Code launched. When the line
        changes role, the focus goes with it, so typed keys never reach Code's shortcuts.
        """
        typing_input, typing_console = self.input.has_focus, self.console.has_focus
        session = self._input_session()[1]
        shown = bool(self.output.display and session and session.state != 'stopped')
        if shown != self.input.display:
            self.input.display = shown
            self.refresh_bindings()  # The footer offers P only while there is a prompt.
        self.sync_console()
        if typing_input and self.console.display:
            self.console.focus()
        elif typing_console and self.input.display:
            self.input.focus()

    def _console_frame(self):
        """The selected paused context and the frame the console evaluates in."""
        context = self.selected
        if (context is None or not context.active or context.session is None
                or context.session.state != 'stopped' or not context.frames):
            return context, None
        return context, context.frames[min(context.frame_row, len(context.frames) - 1)]

    def sync_console(self):
        """Show the console beside the output only while paused; it names its frame."""
        context, frame = self._console_frame()
        paused = bool(context and context.active and context.session is not None
                      and context.session.state == 'stopped')
        shown = bool(self.output.display and paused)
        self.console.placeholder = _console_placeholder(frame)
        if shown != self.console.display:
            self.console.display = shown
            self.refresh_bindings()  # The footer offers : only while paused.

    def _evaluate_console(self, text):
        context, frame = self._console_frame()
        if frame is None:
            self.app.notify('Pause the program to evaluate an expression.', severity='warning')
            return
        self._append_output(context, f'> {text}')
        self._spawn(context, self._console(context, context.generation, context.pause,
                                           text, frame))

    async def _console(self, context, generation, pause, text, frame):
        try:
            value = await context.session.evaluate(text, frame['id'], context='repl')
        except DebugError as error:
            value = _watch_error(error)
        if not self._current(context, generation):
            return
        if value:
            # An assignment has no value; its effect shows in Variables and Watch.
            self._append_output(context, value)
        if self._paused(context, generation, pause):
            try:
                await self._frame(context, generation, pause, frame)
            except DebugError as error:
                if self._paused(context, generation, pause):
                    self.app.notify(str(error), severity='warning')

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
            self._append_output(context, f'[input] {text}')

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
        context.variables = ()
        context.expanded = set()
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
                        f'[{category}] {text.rstrip()}',
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
            session.exception_mode = self.exception_mode(profile.root)
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
        context.variables = ()
        context.execution = None
        context.frame_row = 0
        context.watch_rows = ()
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
            if context.run_to is not None:
                # Any pause ends Run to cursor: the file gets its own breakpoints back.
                (path, _line), context.run_to = context.run_to, None
                self._spawn(context, self._restore_breakpoints(context, generation, path))
            # Controls never wait for inspection, which may be slow or fail.
            self._render_inspection(context)
            exception = body.get('reason') == 'exception'
            self._spawn(context, self._inspect(context, generation, context.pause, exception))
            if exception:
                self._spawn(context, self._show_exception(context, generation, context.pause))
        elif name in {'breakpoint', 'breakpoints'}:
            if self.selected is context:
                self._verification(context)

    async def _show_exception(self, context, generation, pause):
        try:
            text = await context.session.exception_info()
        except DebugError:
            text = None
        if not self._paused(context, generation, pause):
            return
        text = (text or '').strip() or 'Unknown exception'
        self._append_output(context, f'[exception] {text}')
        self._set_state(context, f'Paused on exception: {text.splitlines()[0]} · '
                                 f'{context.profile.name} · {context.profile.root}')

    def _output_title(self, context):
        # The profile is named once, in the title, instead of on every line. The output has
        # only a top border, so the exception mode goes in the title too, never a subtitle.
        mode = self.exception_mode(context.profile.root)
        return f'Debug output · {context.profile.name} · Exceptions: {mode}'

    def exception_mode(self, root):
        return self.exception_modes.get(Path(root).resolve(), DEFAULT_EXCEPTION_MODE)

    def cycle_exceptions(self, root):
        """Move a project to the next exception mode, save it and apply it to its live runs."""
        root = Path(root).resolve()
        modes = EXCEPTION_MODES
        mode = modes[(modes.index(self.exception_mode(root)) + 1) % len(modes)]
        self.exception_modes[root] = mode
        try:
            self.exception_store.save(self.exception_modes)
        except ConfigurationError as error:
            self.app.notify(str(error), severity='warning')
        for context in self.contexts.values():
            if (context.active and context.session is not None
                    and Path(context.profile.root).resolve() == root):
                self._spawn(context, self._apply_exceptions(context, mode))
        if self.selected is not None and Path(self.selected.profile.root).resolve() == root:
            self.output.border_title = self._output_title(self.selected)
        return mode

    async def _apply_exceptions(self, context, mode):
        try:
            await context.session.set_exception_mode(mode)
        except DebugError as error:
            self.app.notify(f'Unable to change exceptions for {context.profile.name}: {error}',
                            severity='warning')

    def _paused(self, context, generation, pause):
        return (self._current(context, generation) and pause == context.pause
                and context.session.state == 'stopped')

    async def _inspect(self, context, generation, pause, exception=False):
        try:
            frames = await context.session.stack()
            if not self._paused(context, generation, pause):
                return
            context.frames = frames
            # An exception can stop inside runtime code (Go's panic.go, Node's fs); show
            # the project's own frame instead. Steps and breakpoints keep the top frame.
            context.frame_row = _own_frame(frames, context.profile.root) if exception else 0
            self._render_pause(context)
            if frames:
                await self._frame(context, generation, pause, frames[context.frame_row])
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
            reference = scope['variablesReference']
            name = scope.get('name', 'Scope')
            values.append(VariableRow(name, reference))
            if not await self._variables(context, generation, pause, values,
                                         VariableRow(name, reference, path=(name,), depth=-1)):
                return
        if not self._paused(context, generation, pause):
            return
        context.watch_frame = frame['id']
        await self._evaluate_watches(context, generation, pause, frame['id'])
        if not self._paused(context, generation, pause):
            return
        context.variables = tuple(values)
        path = frame.get('source', {}).get('path')
        context.execution = (
            (context.profile.root, Path(path), frame.get('line', 1)) if path else None
        )
        self._render_inspection(context)

    async def _variables(self, context, generation, pause, values, holder):
        """Append holder's variables, and the fields of the expanded ones, to values."""
        reference = holder.children or holder.reference
        for value in await context.session.variables(reference):
            if not self._paused(context, generation, pause):
                return False
            children = value.get('variablesReference') or 0
            path = (*holder.path, value['name'])
            variable = VariableRow(
                holder.scope, reference, value['name'], str(value.get('value', '')),
                holder.depth + 1, children, path,
                bool(children) and path in context.expanded
                and holder.depth + 1 < MAX_VARIABLE_DEPTH,
                value.get('evaluateName') or '')
            values.append(variable)
            if variable.expanded and not await self._variables(
                    context, generation, pause, values, variable):
                return False
        return True

    @on(DataTable.RowHighlighted, '#code-variables, #code-watches')
    def _value_highlighted(self, event):
        event.stop()
        self._show_preview()

    def _show_preview(self):
        """The highlighted value in full, wrapped, under the cut-off rows of each table."""
        for table, preview in (('#code-variables', '#variable-preview'),
                               ('#code-watches', '#watch-preview')):
            variable = self.query_one(table, ValueTable).highlighted
            widget = self.query_one(preview, Static)
            widget.display = (variable is not None and variable.name is not None
                              and variable.value != '—')
            widget.update(f'{variable.name} = {variable.value}' if widget.display else '')

    @on(ValueTable.CopyRequested, '#code-variables, #code-watches')
    def copy_variable(self, event):
        event.stop()
        context = self.selected
        if (context is None or not context.active or context.session is None
                or context.session.state != 'stopped'):
            return
        self._spawn(context, self._copy_variable(
            context, context.generation, context.pause, event.variable))

    async def _copy_variable(self, context, generation, pause, variable):
        try:
            text = await copy_text(context.session, variable, context.watch_frame)
        except DebugError:
            text = variable.value  # The fields could not be read: copy what the row shows.
        if self._paused(context, generation, pause):
            self.app.copy_to_clipboard(text)
            self.app.notify(f'Copied the value of {variable.name}', timeout=2)

    @on(ValueTable.Toggled, '#code-variables, #code-watches')
    def toggle_variable(self, event):
        """Right expands a variable's or a watch's fields, Left collapses them."""
        event.stop()
        context = self.selected
        if (context is None or not context.active or context.session is None
                or context.session.state != 'stopped' or not context.frames):
            return
        if event.expanded:
            context.expanded.add(event.variable.path)
        else:
            context.expanded.discard(event.variable.path)
        refresh = (self._refresh_watches if event.control.id == 'code-watches'
                   else self._refresh_frame)
        self._spawn(context, refresh(context, context.generation, context.pause))

    async def _refresh_frame(self, context, generation, pause):
        """Read the selected frame again: values, fields and watches."""
        if not self._paused(context, generation, pause) or not context.frames:
            return
        frame = context.frames[min(context.frame_row, len(context.frames) - 1)]
        try:
            await self._frame(context, generation, pause, frame)
        except DebugError as error:
            if self._paused(context, generation, pause):
                self.app.notify(str(error), severity='warning')

    @on(DataTable.RowSelected, '#code-variables')
    def edit_variable(self, event):
        """Enter (or a click on the selected row) sets the variable to a new value."""
        event.stop()
        context = self.selected
        table = self.query_one('#code-variables', VariablesTable)
        if (context is None or not context.active or context.session is None
                or context.session.state != 'stopped'
                or not hasattr(context.session, 'set_variable')
                or not 0 <= event.cursor_row < len(table.variable_rows)):
            return
        variable = table.variable_rows[event.cursor_row]
        if variable.name is None:
            return  # A scope heading.
        self._editing = (context, context.generation, context.pause, variable)
        pane = self.query_one('#code-variables-pane').region
        content = table.content_region
        prefix = table.cell_padding + cell_len(f'{variable.prefix}{variable.name} = ')
        row_y = content.y - pane.y + event.cursor_row - int(table.scroll_y)
        editor = self.query_one(VariableEditor)
        editor.styles.offset = (content.x - pane.x + prefix, row_y)
        editor.styles.width = max(8, content.width - prefix)
        editor.value = variable.value
        editor.display = True
        editor.cursor_position = len(editor.value)
        table.border_subtitle = "Enter set · Esc cancel · a value in the program's language"
        editor.focus()

    def _hide_variable_editor(self):
        editor = self.query_one(VariableEditor)
        refocus = editor.has_focus
        self._editing = None
        editor.display = False
        table = self.query_one('#code-variables', VariablesTable)
        table.border_subtitle = ''
        return table, refocus

    def _close_variable_editor(self):
        table, _ = self._hide_variable_editor()
        table.focus()

    @on(Input.Submitted, '#variable-value')
    def _variable_submitted(self, event):
        event.stop()
        editing = self._editing
        self._close_variable_editor()
        if editing is None:
            return
        context, generation, pause, variable = editing
        if self._paused(context, generation, pause):
            self._spawn(context, self._set_variable(
                context, generation, pause, variable, event.value))

    async def _set_variable(self, context, generation, pause, variable, value):
        try:
            await context.session.set_variable(variable.reference, variable.name, value)
        except DebugError as error:
            if self._paused(context, generation, pause):
                self.app.notify(f'Cannot set {variable.name}: {error}', severity='warning')
            return
        # Read the frame again: other variables and watches may depend on it.
        await self._refresh_frame(context, generation, pause)

    @on(DataTable.RowSelected, '#code-stack')
    def select_frame(self, event):
        context = self.selected
        if context is not None and context.active and context.session.state == 'stopped':
            context.pause += 1
            context.variables = ()
            context.execution = None
            context.watch_rows = ()
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

    def run_to_cursor(self, path, line):
        """Continue to a source line through a breakpoint that lasts until the next pause.

        Returns why it cannot run, or None. A breakpoint met first stops there instead.
        """
        context = self.selected
        if (context is None or not context.active or context.session is None
                or context.session.state != 'stopped'):
            return 'Run to cursor works while the program is paused.'
        root = context.profile.root
        if not Path(path).resolve().is_relative_to(Path(root).resolve()):
            return "Run to cursor works in the debugged profile's files."
        options = self.browser.options_snapshot(root).get(str(path), {})
        if any(option.hit_condition for option in options.values()):
            # Sending this file's breakpoints again would restart their hit counts.
            return ('Run to cursor is not available in a file with hit-count breakpoints: '
                    'it would restart their counts.')
        self._invalidate(context)
        self._spawn(context, self._run_to(context, context.generation, str(path), line))
        return None

    async def _run_to(self, context, generation, path, line):
        root = context.profile.root
        try:
            async with context.update_lock:
                if not self._current(context, generation):
                    return
                lines = self.browser.breakpoint_snapshot(root).get(path, ())
                options = self.browser.options_snapshot(root).get(path) or {}
                if line not in lines or line in options:
                    # A plain stop on the line: its own condition or log message would let
                    # the program go past it.
                    context.run_to = (path, line)
                    lines, options = _with_run_to(lines, options, line)
                    await context.session.set_breakpoints(
                        path, lines, *((options,) if options else ()))
            if self._current(context, generation):
                await context.session.continue_execution()
        except DebugError as error:
            if self._current(context, generation):
                self.app.notify(str(error), severity='warning')

    async def _restore_breakpoints(self, context, generation, path):
        root = context.profile.root
        async with context.update_lock:
            if not self._current(context, generation):
                return
            lines = self.browser.breakpoint_snapshot(root).get(path, ())
            options = self.browser.options_snapshot(root).get(path)
            try:
                await context.session.set_breakpoints(
                    path, lines, *((options,) if options else ()))
            except DebugError as error:
                if self._current(context, generation):
                    self.app.notify(str(error), severity='warning')
                return
            if self._current(context, generation) and self.selected is context:
                self._verification(context)

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
                    if context.run_to is not None and context.run_to[0] == str(path):
                        # Editing marks while running to the cursor keeps the target line.
                        lines, options = _with_run_to(lines, options or {}, context.run_to[1])
                    await context.session.set_breakpoints(
                        str(path), lines, *((options,) if options else ()))
                    if self._current(context, generation) and self.selected is context:
                        self._verification(context)
            except DebugError as error:
                if self._current(context, generation):
                    self.app.notify(str(error), severity='warning')

    async def close_context(self, context):
        if context.close_task is None:
            context.run_to = None  # A one-shot target never outlives its session.
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
                    context, f'[stderr] Warning: {warning}'
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
