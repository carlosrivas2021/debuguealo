"""Owned Delve DAP session for a deliberately bounded Go command grammar."""

import asyncio
import contextlib
import shutil
import socket
import tempfile
from pathlib import Path

from debugpilot.debugger.dap import DAPClient, DebugError
from debugpilot.debugger.python import (
    PythonDebugSession,
    _environment,
    _intent,
    _profile_variables,
)
from debugpilot.storage.code_projects import CodeProject
from debugpilot.terminal.code_session import CodeSession, command_argv

_GRAMMAR = (
    'Supported Go commands: go run main.go [args...] or go run . [args...]. '
    'Other Go forms are unsupported; F5 remains unchanged. No run-mode fallback.'
)


def _target(profile):
    command = profile.command
    if len(command) < 3 or Path(command[0]).name.lower() != 'go' or command[1] != 'run':
        raise DebugError(_GRAMMAR)
    target = command[2]
    if target not in {'main.go', '.'}:
        raise DebugError(_GRAMMAR)
    args = command[3:]
    if any(arg.endswith('.go') for arg in args):
        raise DebugError(_GRAMMAR)
    try:
        argv = command_argv(command, _environment(profile))
    except RuntimeError as error:
        message = f'{error}. Select an installed Go runtime. No run-mode fallback.'
        raise DebugError(message) from error
    program = str(profile.root / target) if target == 'main.go' else str(profile.root)
    return argv[0], program, args


# Delve's exceptionBreakpointFilters. A recovered panic never reaches the debugger, so
# pausing on every exception is the same as pausing on the uncaught ones.
GO_EXCEPTION_FILTERS = {
    'uncaught': ('unrecovered-panic', 'runtime-fatal-throw'),
    'all': ('unrecovered-panic', 'runtime-fatal-throw'),
    'none': (),
}


class GoDebugSession(PythonDebugSession):
    """One Go/Delve session with the same events and inspection API as Python debug."""

    VALUE_REPR = False  # Delve cannot run code to serialize a value.
    EXCEPTION_FILTERS = GO_EXCEPTION_FILTERS

    # Delve reports the program's output over DAP; its terminal holds only Delve's own.
    terminal_output = False

    def __init__(self, on_event=None, on_output=None, *, timeout=15):
        super().__init__(on_event, on_output, timeout=timeout)
        self._build_dir = None

    async def start(self, profile, breakpoints, options=None):
        if self.state not in {'idle', 'closed'}:
            raise DebugError('A debug session is already active; Stop before starting again.')
        _, program, args = _target(profile)
        variables = _profile_variables(profile)
        environment = _environment(profile)
        dlv = (shutil.which('dlv') if environment is None
               else shutil.which('dlv', path=environment.get('PATH')))
        if not dlv:
            message = ('Delve (dlv) is required for Go debugging; install it and add it to PATH. '
                       'No run-mode fallback.')
            raise DebugError(message)
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
                with socket.socket() as reservation:
                    reservation.bind(('127.0.0.1', 0))
                    port = reservation.getsockname()[1]
                self._build_dir = tempfile.TemporaryDirectory(prefix='debugpilot-go-build-')
                output = str(Path(self._build_dir.name) / 'debugpilot-target')
                self._adapter = CodeSession(self._adapter_output, self._adapter_exit)
                await self._adapter.open_command(
                    (dlv, 'dap', '--listen', f'127.0.0.1:{port}'), self.profile.root)
                self._emit({'event': 'adapterStarted', 'body': {}})
                while True:
                    if self._adapter.process is None:
                        raise DebugError(self._startup_error(dlv))
                    try:
                        reader, writer = await asyncio.open_connection('127.0.0.1', port)
                        break
                    except OSError:
                        await asyncio.sleep(0.03)
                self._client = DAPClient(reader, writer, self._event, timeout=self.timeout)
                await self._client.request('initialize', {
                    'clientID': 'debugpilot', 'adapterID': 'go', 'pathFormat': 'path',
                    'linesStartAt1': True, 'columnsStartAt1': True,
                    'supportsRunInTerminalRequest': False,
                })
            # Delve compiles the program while handling launch. A cold or large build can
            # outlast the startup timeout without anything being wrong, so the build has no
            # deadline; Stop cancels it like any other startup step.
            launch = asyncio.create_task(self._client.request('launch', {
                'name': self.profile.name, 'type': 'go', 'request': 'launch',
                'mode': 'debug', 'program': program, 'cwd': str(self.profile.root),
                'args': list(args), 'output': output, 'outputMode': 'remote',
                'buildFlags': '-buildvcs=false', 'stopOnEntry': False,
                **({'env': variables} if variables else {}),
            }, deadline=None))
            self._state('building')
            initialized = asyncio.create_task(self._initialized.wait())
            try:
                await asyncio.wait({launch, initialized}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                initialized.cancel()
            if not self._initialized.is_set():
                # A build error ends launch without initializing; report it right away.
                try:
                    await launch
                except DebugError as error:
                    if error.detail:
                        message = f'Unable to build the Go program: {error.detail}'
                        raise DebugError(message) from None
                    # Delve died or refused launch: keep the usual startup error with the reason.
                    self._diagnostic = f'{self._diagnostic.strip()}\n{error}'.strip()
                    raise DebugError(self._startup_error(dlv)) from None
            self._state('starting')
            async with asyncio.timeout(self.timeout):
                await self._initialized.wait()
                for source, lines in intent.items():
                    await self.set_breakpoints(source, lines, start_options.get(source))
                await self._apply_exception_mode()
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
                raise DebugError(self._startup_error(dlv)) from None
            if isinstance(error, (OSError, RuntimeError)) and not isinstance(error, DebugError):
                raise DebugError(f'Unable to debug Go: {error}') from error
            raise
        finally:
            self._starting = None

    def _startup_error(self, dlv):
        return (f'Unable to start Go debugging with Delve at {dlv}. Check Go/Delve compatibility '
                f'and local same-user process permissions. No run-mode fallback. Diagnostics: '
                f'{self._diagnostic.strip() or "startup timed out"}')

    async def _cleanup(self):
        await super()._cleanup()
        if self._build_dir is not None:
            self._build_dir.cleanup()
            self._build_dir = None
