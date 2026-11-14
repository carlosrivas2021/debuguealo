"""Owned debugpy adapter with a deliberately bounded Python command grammar."""

import asyncio
import contextlib
import re
import socket
import sys
from pathlib import Path

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.debugger.dap import DAPClient, DebugError
from debugpilot.storage.breakpoints import BreakpointOptions
from debugpilot.storage.code_projects import CodeProject, profile_environment, profile_variables
from debugpilot.terminal.code_session import CodeSession, command_argv

_GRAMMAR = (
    'Supported Python commands: python[3] [-u] script.py [args...] or '
    'python[3] [-u] -m package.module [args...]; an explicit Python interpreter '
    '(including a virtualenv) is allowed. Remove other interpreter flags; F5 remains run-only.'
)


def _target(profile):
    command = profile.command
    if not command or not re.fullmatch(r'python(?:\d+(?:\.\d+)?)?(?:\.exe)?',
                                      Path(command[0]).name, re.IGNORECASE):
        raise DebugError(_GRAMMAR)
    tail = list(command[1:])
    if tail and tail[0] == '-u':
        tail.pop(0)
    if not tail:
        raise DebugError(_GRAMMAR)
    if tail[0] == '-m':
        if len(tail) < 2 or not re.fullmatch(r'\w+(?:\.\w+)*', tail[1], re.ASCII):
            raise DebugError(_GRAMMAR)
        target = {'module': tail[1], 'args': tail[2:]}
    elif tail[0].startswith('-') or Path(tail[0]).suffix.lower() != '.py':
        raise DebugError(_GRAMMAR)
    else:
        source = Path(tail[0])
        target = {'program': str(profile.root / source), 'args': tail[1:]}
    try:
        # The profile's PATH picks the interpreter, as it does for Run.
        argv = command_argv(command, _environment(profile))
    except RuntimeError as error:
        raise DebugError(str(error)) from error
    return argv[0], target


def _breakpoints(root, source, lines):
    path = Path(source)
    path = path if path.is_absolute() else root / path
    intent = tuple(sorted(set(lines)))
    if any(type(line) is not int or line < 1 for line in intent):
        raise DebugError('Breakpoints require positive 1-based integer lines.')
    return str(path), intent


def _environment(profile):
    """The profile's full environment (None without env/envFile), as a debug error."""
    try:
        return profile_environment(profile)
    except ConfigurationError as error:
        raise DebugError(str(error)) from None


def _profile_variables(profile):
    """The profile's env/envFile variables, with configuration errors as debug errors."""
    try:
        return profile_variables(profile)
    except ConfigurationError as error:
        raise DebugError(str(error)) from None


def _line_options(lines, options):
    """Options of the requested lines only; anything else never reaches an adapter."""
    selected = {}
    for line, option in (options or {}).items():
        if line not in lines or option is None:
            continue
        if not isinstance(option, BreakpointOptions):
            raise DebugError('Breakpoint options must be BreakpointOptions.')
        selected[line] = option
    return selected


def _source_breakpoints(lines, options):
    """DAP SourceBreakpoint entries; a line without options stays {'line': n}."""
    entries = []
    for line in lines:
        entry = {'line': line}
        option = options.get(line)
        if option is not None and option.condition:
            entry['condition'] = option.condition
        if option is not None and option.log_message:
            entry['logMessage'] = option.log_message
        if option is not None and option.hit_condition:
            entry['hitCondition'] = option.hit_condition
        entries.append(entry)
    return entries


def _intent(root, breakpoints, options):
    """Normalized path -> lines, and the caller's options under the same normalized key."""
    intent, by_path = {}, {}
    for source, lines in breakpoints.items():
        path, lines = _breakpoints(root, source, lines)
        intent[path] = lines
        by_path[path] = (options or {}).get(source)
    return intent, by_path


class PythonDebugSession:
    """One active immutable profile snapshot; callbacks are synchronous/nonblocking."""

    def __init__(self, on_event=None, on_output=None, *, timeout=15):
        self.events = asyncio.Queue()
        self.on_event = on_event
        self.on_output = on_output
        self.timeout = timeout
        self.state = 'idle'
        self.profile = None
        self.thread_id = None
        self.exit_code = None
        self.requested_breakpoints = {}
        self.verified_breakpoints = {}
        self.breakpoint_options = {}
        self._adapter = None
        self._client = None
        self._starting = None
        self._cleanup_lock = asyncio.Lock()
        self._cleanup_task = None
        self._initialized = asyncio.Event()
        self._diagnostic = ''

    def _emit(self, message):
        self.events.put_nowait(message)
        if self.on_event:
            self.on_event(message)

    def _state(self, state):
        self.state = state
        self._emit({'event': 'state', 'body': {'state': state}})

    def _event(self, message):
        name, body = message.get('event'), message.get('body', {})
        if name == 'initialized':
            self._initialized.set()
        elif name == 'stopped':
            self.thread_id = body.get('threadId')
            self._state('stopped')
        elif name == 'continued':
            self.thread_id = None
            self._state('running')
        elif name == 'exited':
            self.exit_code = body.get('exitCode')
        elif name == 'output' and self.on_output and body.get('category') != 'telemetry':
            # DAP telemetry is for tools, never user-visible output.
            self.on_output(body.get('category', 'console'), body.get('output', ''))
        elif name == 'breakpoint':
            # Adapter changes verification only, never overwrite requested lines.
            breakpoint = body.get('breakpoint', {})
            for entries in self.verified_breakpoints.values():
                for index, entry in enumerate(entries):
                    if entry.get('id') == breakpoint.get('id'):
                        entries[index] = breakpoint
        self._emit(message)
        if name in {'terminated', 'transportClosed'} and self.state not in {'closed', 'closing'}:
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._cleanup())

    def _adapter_output(self, text):
        # Adapter diagnostics are not target stdout; retain a bounded startup tail.
        self._diagnostic = (self._diagnostic + text)[-8192:]

    def _adapter_exit(self):
        if self._client is not None and self.state not in {'closing', 'closed'}:
            self._event({'event': 'adapterExited', 'body': {
                'message': self._diagnostic, 'exitCode': self._adapter.exit_code,
            }})
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._cleanup())

    async def start(self, profile, breakpoints, options=None):
        if self.state not in {'idle', 'closed'}:
            raise DebugError('A debug session is already active; Stop before starting again.')
        interpreter, target = _target(profile)
        variables = _profile_variables(profile)
        intent, start_options = _intent(profile.root, breakpoints, options)
        self.profile = CodeProject(profile.name, Path(profile.root), tuple(profile.command))
        self.requested_breakpoints = intent
        self.verified_breakpoints = {}
        self.breakpoint_options = {}
        self.exit_code = None
        self.thread_id = None
        self.events = asyncio.Queue()
        self._initialized.clear()
        self._diagnostic = ''
        self._starting = asyncio.current_task()
        self._state('starting')
        launch = None
        try:
            async with asyncio.timeout(self.timeout):
                # Reserve an ephemeral loopback port; debugpy binds the same address.
                with socket.socket() as reservation:
                    reservation.bind(('127.0.0.1', 0))
                    port = reservation.getsockname()[1]
                self._adapter = CodeSession(self._adapter_output, self._adapter_exit)
                # The adapter runs on debugealo's own interpreter and bundled debugpy;
                # debugpy's launcher runs the target with the profile's interpreter.
                await self._adapter.open_command(
                    (sys.executable, '-m', 'debugpy.adapter', '--host', '127.0.0.1',
                     '--port', str(port)), self.profile.root,
                )
                self._emit({'event': 'adapterStarted', 'body': {}})
                while True:
                    if self._adapter.process is None:
                        raise DebugError(self._startup_error(interpreter))
                    try:
                        reader, writer = await asyncio.open_connection('127.0.0.1', port)
                        break
                    except OSError:
                        await asyncio.sleep(0.03)
                self._client = DAPClient(reader, writer, self._event, timeout=self.timeout)
                await self._client.request('initialize', {
                    'clientID': 'debugpilot', 'adapterID': 'python', 'pathFormat': 'path',
                    'linesStartAt1': True, 'columnsStartAt1': True,
                    'supportsRunInTerminalRequest': False,
                })
                launch = asyncio.create_task(self._client.request('launch', {
                    'name': self.profile.name, 'type': 'debugpy', 'request': 'launch',
                    'python': interpreter, 'cwd': str(self.profile.root),
                    'console': 'internalConsole', 'redirectOutput': True,
                    'subProcess': False, 'justMyCode': True,
                    'pythonArgs': ['-u'] if '-u' in profile.command[1:2] else [],
                    **({'env': variables} if variables else {}),
                    **target,
                }))
                await self._initialized.wait()
                for source, lines in intent.items():
                    await self.set_breakpoints(source, lines, start_options.get(source))
                await self._client.request('configurationDone')
                await launch
                if self.state == 'starting':
                    self._state('running')
        except BaseException as error:
            if launch is not None:
                launch.cancel()
                with contextlib.suppress(asyncio.CancelledError, DebugError):
                    await launch
            await self._cleanup()
            if isinstance(error, TimeoutError):
                raise DebugError(self._startup_error(interpreter)) from None
            if isinstance(error, (OSError, RuntimeError)) and not isinstance(error, DebugError):
                raise DebugError(f'Unable to debug Python: {error}') from error
            raise
        finally:
            self._starting = None

    def _startup_error(self, interpreter):
        return (
            f'Python debugging failed to start with "{interpreter}". Check that this '
            f'interpreter runs and is a Python version supported by debugpy. No run-mode '
            f'fallback. Diagnostics: {self._diagnostic.strip() or "startup timed out"}'
        )

    async def set_breakpoints(self, source, lines, options=None):
        if self.profile is None or self._client is None:
            raise DebugError('No active debug session.')
        path, intent = _breakpoints(self.profile.root, source, lines)
        line_options = _line_options(intent, options)
        result = await self._client.request('setBreakpoints', {
            'source': {'path': path}, 'breakpoints': _source_breakpoints(intent, line_options),
            'sourceModified': False,
        })
        self.requested_breakpoints[path] = intent
        self.breakpoint_options[path] = line_options
        self.verified_breakpoints[path] = result.get('breakpoints', [])
        self._emit({'event': 'breakpoints', 'body': {'path': path,
                    'requested': intent, 'verified': self.verified_breakpoints[path]}})
        return self.verified_breakpoints[path]

    def _stopped(self):
        if self.state != 'stopped' or self.thread_id is None or self._client is None:
            raise DebugError('Pause at a breakpoint before inspecting or stepping.')
        return self.thread_id

    async def stack(self):
        thread = self._stopped()
        return (await self._client.request('stackTrace', {
            'threadId': thread, 'startFrame': 0, 'levels': 100,
        })).get('stackFrames', [])

    async def scopes(self, frame_id):
        self._stopped()
        return (await self._client.request('scopes', {'frameId': frame_id})).get('scopes', [])

    async def variables(self, reference):
        self._stopped()
        return (await self._client.request('variables', {
            'variablesReference': reference, 'start': 0, 'count': 200,
        })).get('variables', [])

    async def evaluate(self, expression, frame_id):
        """Evaluate a watch expression in a paused frame; the debugger's error is raised."""
        self._stopped()
        try:
            body = await self._client.request('evaluate', {
                'expression': expression, 'frameId': frame_id, 'context': 'watch',
            })
        except DebugError as error:
            # Delve keeps the reason in the response detail ("could not find symbol ...").
            if error.detail:
                raise DebugError(error.detail) from None
            raise
        return str(body.get('result', ''))

    async def _resume(self, command):
        thread = self._stopped()
        # Clear stale thread state before awaiting: a stopped event can precede the response.
        self.thread_id = None
        self._state('running')
        try:
            return await self._client.request(command, {'threadId': thread})
        except DebugError:
            if self.state == 'running':
                self.thread_id = thread
                self._state('stopped')
            raise

    # The debugged program inherits stdin from the PTY this session opens for its adapter.
    supports_input = True

    def _input_terminal(self):
        if not self.supports_input:
            raise DebugError('Program input is not available for an attached process.')
        if self._adapter is None or self.state not in {'running', 'stopped'}:
            raise DebugError('No running program to send input to.')
        return self._adapter

    def send_input(self, text):
        """Type one line into the debugged program, as Enter would in a terminal."""
        self._input_terminal().write(f'{text}\r')

    def send_eof(self):
        """End of input (Ctrl+D): a program reading until EOF stops reading."""
        self._input_terminal().end_input()

    def input_echo(self):
        """Whether the UI should show typed input: only while the program echoes it.

        Output arrives over DAP, so the terminal's own echo never reaches it; a program
        that turns echo off (getpass) keeps its input hidden. Unknown means echo.
        """
        if self._adapter is None:
            return True
        echo = self._adapter.echo_enabled()
        return True if echo is None else echo

    async def continue_execution(self):
        return await self._resume('continue')

    async def step_over(self):
        return await self._resume('next')

    async def step_in(self):
        return await self._resume('stepIn')

    async def step_out(self):
        return await self._resume('stepOut')

    async def close(self):
        starting = self._starting
        if starting is not None and starting is not asyncio.current_task():
            starting.cancel()
            with contextlib.suppress(asyncio.CancelledError, DebugError):
                await starting
        await self._cleanup()
        cleanup = self._cleanup_task
        if cleanup is not None and cleanup is not asyncio.current_task():
            await cleanup

    async def _cleanup(self):
        async with self._cleanup_lock:
            if self.state == 'closed':
                return
            self._state('closing')
            completed = False
            try:
                try:
                    client, self._client = self._client, None
                    if client is not None:
                        await client.close()
                finally:
                    if self._adapter is not None:
                        await self._adapter.close_session()
                completed = True
            finally:
                if completed:
                    self._adapter = None
                    self.thread_id = None
                    self.verified_breakpoints = {}
                    self._state('closed')
