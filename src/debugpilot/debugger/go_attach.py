"""Non-owning DAP session for attaching to an existing remote Delve target."""

import asyncio
import contextlib
from pathlib import Path, PurePosixPath

from debugpilot.debugger.dap import DAPClient, DebugError
from debugpilot.debugger.python import PythonDebugSession, _breakpoints
from debugpilot.storage.code_projects import CodeProject, parse_go_attach


class GoAttachSession(PythonDebugSession):
    """Go inspection API over an existing loopback Delve DAP endpoint."""

    def __init__(self, on_event=None, on_output=None, *, timeout=15):
        super().__init__(on_event, on_output, timeout=timeout)
        self._disconnect_sent = False
        self._remote_root = None
        self._local_root = None
        self._registered_sources = {}
        self._configured = False
        self._target_stopped = False
        self._target_thread_id = None
        self._go_cleanup_lock = asyncio.Lock()
        self.disconnect_warning = None

    @staticmethod
    def _configuration(profile):
        attach = getattr(profile, 'go_attach', None)
        try:
            return parse_go_attach({
                'host': attach.host,
                'port': attach.port,
                'remoteRoot': attach.remote_root,
            })
        except (AttributeError, TypeError, ValueError):
            raise DebugError(
                'Invalid goAttach: use host 127.0.0.1, integer port 1..65535, '
                'and an absolute POSIX remoteRoot without parent segments.'
            ) from None

    async def start(self, profile, breakpoints):
        if self.state not in {'idle', 'closed'}:
            raise DebugError('A debug session is already active; Stop before starting again.')
        attach = self._configuration(profile)
        intent = {}
        for source, lines in breakpoints.items():
            local, _, validated = await asyncio.to_thread(
                self._local_source_for, profile.root, source, lines)
            intent[str(local)] = validated
        self._local_root = await asyncio.to_thread(Path(profile.root).resolve)
        self.profile = CodeProject(profile.name, self._local_root, tuple(profile.command),
                                   getattr(profile, 'node_debug', None), attach)
        self._remote_root = PurePosixPath(attach.remote_root)
        self.requested_breakpoints = intent
        self.verified_breakpoints = {}
        self.exit_code = None
        self.thread_id = None
        self.events = asyncio.Queue()
        self._initialized.clear()
        self._diagnostic = ''
        self._disconnect_sent = False
        self._registered_sources = {}
        self._configured = False
        self._target_stopped = False
        self._target_thread_id = None
        self.disconnect_warning = None
        self._starting = asyncio.current_task()
        self._state('starting')
        attach_request = None
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.open_connection(attach.host, attach.port)
                self._client = DAPClient(reader, writer, self._event, timeout=self.timeout)
                await self._client.request('initialize', {
                    'clientID': 'debugpilot', 'adapterID': 'go', 'pathFormat': 'path',
                    'linesStartAt1': True, 'columnsStartAt1': True,
                    'supportsRunInTerminalRequest': False,
                })
                attach_request = asyncio.create_task(self._client.request('attach', {
                    'name': profile.name, 'type': 'go', 'request': 'attach', 'mode': 'remote',
                    'host': attach.host, 'port': attach.port,
                    'substitutePath': [{'from': str(self._local_root),
                                        'to': attach.remote_root}],
                }))
                await self._initialized.wait()
                for source, lines in intent.items():
                    await self.set_breakpoints(source, lines)
                await self._client.request('configurationDone')
                await attach_request
                self._configured = True
                if self.state == 'starting':
                    self._state('running')
        except BaseException as error:
            if attach_request is not None:
                attach_request.cancel()
                with contextlib.suppress(asyncio.CancelledError, DebugError):
                    await attach_request
            await self._cleanup()
            if isinstance(error, TimeoutError):
                raise DebugError('Timed out attaching to the existing Go/Delve target.') from None
            if isinstance(error, (OSError, RuntimeError)) and not isinstance(error, DebugError):
                raise DebugError(f'Unable to attach to Go/Delve: {error}') from error
            raise
        finally:
            self._starting = None

    @staticmethod
    def _local_source_for(root_value, source, lines):
        root = Path(root_value).resolve()
        path, intent = _breakpoints(root, source, lines)
        local = Path(path).resolve()
        try:
            relative = local.relative_to(root)
        except ValueError:
            raise DebugError('Go attach source must be inside the workspace folder.') from None
        return local, relative, intent

    async def set_breakpoints(self, source, lines):
        if self.profile is None or self._client is None:
            raise DebugError('No active debug session.')
        local_path, relative, validated = await asyncio.to_thread(
            self._local_source_for, self._local_root, source, lines)
        remote_path = (self._remote_root / PurePosixPath(relative.as_posix())).as_posix()
        result = await self._client.request('setBreakpoints', {
            'source': {'path': remote_path},
            'breakpoints': [{'line': line} for line in validated], 'sourceModified': False,
        })
        key = str(local_path)
        if validated:
            self._registered_sources[remote_path] = key
        else:
            self._registered_sources.pop(remote_path, None)
        self.requested_breakpoints[key] = validated
        self.verified_breakpoints[key] = result.get('breakpoints', [])
        self._emit({'event': 'breakpoints', 'body': {'path': key,
                    'requested': validated, 'verified': self.verified_breakpoints[key]}})
        return self.verified_breakpoints[key]

    async def stack(self):
        frames = await super().stack()
        for frame in frames:
            source = frame.get('source', {}).get('path')
            if not isinstance(source, str):
                continue
            local = await asyncio.to_thread(self._mapped_local_source, source)
            if local is not None:
                frame['source']['path'] = str(local)
        return frames

    def _mapped_local_source(self, source):
        remote = PurePosixPath(source)
        try:
            relative = remote.relative_to(self._remote_root)
        except ValueError:
            return None
        local = (self._local_root / Path(*relative.parts)).resolve()
        try:
            local.relative_to(self._local_root)
        except ValueError:
            return None
        return local

    def _event(self, message):
        name, body = message.get('event'), message.get('body', {})
        if name == 'stopped':
            self._target_stopped = True
            self._target_thread_id = body.get('threadId')
        elif name == 'continued':
            self._target_stopped = False
            self._target_thread_id = None
        if self.state in {'closing', 'closed'} and name in {'stopped', 'continued'}:
            self._emit(message)
            return
        super()._event(message)

    async def _cleanup(self):
        async with self._go_cleanup_lock:
            if self.state == 'closed':
                return
            self._state('closing')
            client = self._client
            failure = None
            if client is not None and self._configured:
                for remote_path in tuple(self._registered_sources):
                    try:
                        await client.request('setBreakpoints', {
                            'source': {'path': remote_path}, 'breakpoints': [],
                            'sourceModified': False,
                        })
                    except (DebugError, OSError, TimeoutError) as error:
                        failure = f'Unable to clear Go session breakpoints: {error}'
                        break
                if failure is None and self._target_stopped and self._target_thread_id is not None:
                    try:
                        await client.request('continue', {
                            'threadId': self._target_thread_id,
                        })
                        self._target_stopped = False
                        self._target_thread_id = None
                    except (DebugError, OSError, TimeoutError) as error:
                        failure = f'Unable to resume the Go target on disconnect: {error}'
            if client is not None and not self._disconnect_sent:
                self._disconnect_sent = True
                try:
                    await client.request('disconnect', {'terminateDebuggee': False})
                except (DebugError, OSError, TimeoutError) as error:
                    if failure is None:
                        failure = f'Unable to confirm Go target disconnect: {error}'
            if failure is not None:
                self.disconnect_warning = failure
                self._emit({'event': 'warning', 'body': {'message': failure}})
                if self.on_output is not None:
                    self.on_output('stderr', f'Warning: {failure}\n')
            await super()._cleanup()
            self._registered_sources.clear()
            self._configured = False
            self._target_stopped = False
            self._target_thread_id = None
            self._remote_root = None
            self._local_root = None
