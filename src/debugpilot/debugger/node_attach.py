"""Attach to an existing loopback Node Inspector without owning its process."""

import asyncio
import contextlib
import json
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from debugpilot.debugger.dap import DebugError
from debugpilot.debugger.inspector import InspectorClient
from debugpilot.debugger.node import NodeDebugSession, cdp_condition, hit_key
from debugpilot.debugger.python import _breakpoints, _line_options
from debugpilot.storage.code_projects import CodeProject, parse_remote_attach

_TARGET = 'Node/Inspector'
_LIST_LIMIT = 64 * 1024


async def _inspector_path(port):
    """Return the WebSocket path of the single Node target behind a loopback port.

    The caller bounds the whole exchange with its attach timeout.
    """
    reader, writer = await asyncio.open_connection('127.0.0.1', port, limit=_LIST_LIMIT)
    try:
        writer.write(f'GET /json/list HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n'
                     'Connection: close\r\n\r\n'.encode())
        await writer.drain()
        header = await reader.readuntil(b'\r\n\r\n')
        lines = header.split(b'\r\n')
        # Node answers with HTTP/1.0 even to a 1.1 request.
        if lines[0].split(b' ', 2)[:2] not in ([b'HTTP/1.0', b'200'], [b'HTTP/1.1', b'200']):
            raise ValueError('the port did not answer as a Node Inspector')
        fields = {k.strip().lower(): v.strip() for k, v in
                  (line.split(b':', 1) for line in lines[1:] if b':' in line)}
        if b'content-length' in fields:
            try:
                length = int(fields[b'content-length'])
            except ValueError:
                raise ValueError('the port did not answer as a Node Inspector') from None
            if not 0 <= length <= _LIST_LIMIT:
                raise ValueError('the Inspector target list is too large')
            body = await reader.readexactly(length)
        else:
            # Without Content-Length the body ends when the peer closes the connection.
            body = b''
            while chunk := await reader.read(_LIST_LIMIT + 1 - len(body)):
                body += chunk
                if len(body) > _LIST_LIMIT:
                    raise ValueError('the Inspector target list is too large')
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        raise ValueError('the port did not answer as a Node Inspector') from None
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    try:
        targets = json.loads(body)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError('the port did not answer as a Node Inspector') from None
    candidates = [t['webSocketDebuggerUrl'] for t in targets if isinstance(t, dict)
                  and t.get('type') == 'node'
                  and isinstance(t.get('webSocketDebuggerUrl'), str)] \
        if isinstance(targets, list) else []
    if len(candidates) != 1:
        raise ValueError(f'expected one Node target, found {len(candidates)}')
    url = urlsplit(candidates[0])
    # Node echoes the Host header it received, so a loopback request gets a loopback URL.
    if url.scheme != 'ws' or url.hostname != '127.0.0.1':
        raise ValueError('the Inspector advertised a non-loopback WebSocket endpoint')
    return url.path


class NodeAttachSession(NodeDebugSession):
    """Node inspection API over an existing loopback Inspector this session does not own.

    Breakpoints are set on the target's paths under remoteRoot and stack frames are mapped
    back to the workspace. Disconnect removes this session's breakpoints, resumes a paused
    target and closes the connection; the Node process keeps running.
    """

    attach_field = 'node_attach'
    config_name = 'nodeAttach'
    language = 'Node'

    def __init__(self, on_event=None, on_output=None, *, timeout=15):
        super().__init__(on_event, on_output, timeout=timeout)
        self._remote_root = None
        self._local_root = None
        self._target_paused = False
        self._transport_lost = False
        self._attach_cleanup_lock = asyncio.Lock()
        self.disconnect_warning = None

    def _configuration(self, profile):
        attach = getattr(profile, self.attach_field, None)
        try:
            return parse_remote_attach({
                'host': attach.host,
                'port': attach.port,
                'remoteRoot': attach.remote_root,
            })
        except (AttributeError, TypeError, ValueError):
            raise DebugError(
                f'Invalid {self.config_name}: use host 127.0.0.1, integer port 1..65535, '
                'and an absolute POSIX remoteRoot without parent segments.'
            ) from None

    def _cdp_event(self, message):
        method = message.get('method')
        if method == 'Debugger.paused':
            self._target_paused = True
        elif method == 'Debugger.resumed':
            self._target_paused = False
        elif method == 'transportClosed' and not self._exiting:
            self._transport_lost = True
        if self.state in {'closing', 'closed'} and method in {
                'Debugger.paused', 'Debugger.resumed'}:
            return
        super()._cdp_event(message)

    async def start(self, profile, breakpoints, options=None):
        if self.state not in {'idle', 'closed'}:
            raise DebugError('A debug session is already active; Stop before starting again.')
        attach = self._configuration(profile)
        intent, start_options = {}, {}
        for source, lines in breakpoints.items():
            local, _, validated = await asyncio.to_thread(
                self._local_source_for, profile.root, source, lines)
            intent[str(local)] = validated
            start_options[str(local)] = (options or {}).get(source)
        self._local_root = await asyncio.to_thread(Path(profile.root).resolve)
        self.profile = CodeProject(profile.name, self._local_root, tuple(profile.command),
                                   getattr(profile, 'node_debug', None), node_attach=attach)
        self._remote_root = PurePosixPath(attach.remote_root)
        self.requested_breakpoints = intent
        self.verified_breakpoints = {}
        self.breakpoint_options = {}
        self.exit_code = None
        self.thread_id = None
        self.events = asyncio.Queue()
        self._paused.clear()
        self._initial = False
        self._frames = []
        self._scripts = {}
        self._objects = {}
        self._exiting = False
        self._target_paused = False
        self._transport_lost = False
        self.disconnect_warning = None
        self._starting = asyncio.current_task()
        self._state('starting')
        try:
            async with asyncio.timeout(self.timeout):
                try:
                    path = await _inspector_path(attach.port)
                    self._client = await InspectorClient.connect(
                        f'ws://127.0.0.1:{attach.port}{path}', self._cdp_event,
                        timeout=self.timeout)
                except (DebugError, OSError, ValueError) as error:
                    raise DebugError(f'Unable to attach to {_TARGET}: {error}') from error
                await self._client.request('Runtime.enable')
                await self._client.request('Debugger.enable')
                for source, lines in intent.items():
                    await self.set_breakpoints(source, lines, start_options.get(source))
                # Releases a target started with --inspect-brk; a no-op otherwise.
                await self._client.request('Runtime.runIfWaitingForDebugger')
                if self.state == 'starting':
                    self._state('running')
        except BaseException as error:
            await self._cleanup()
            if isinstance(error, TimeoutError):
                raise DebugError(
                    f'Timed out attaching to the existing {_TARGET} target.') from None
            raise
        finally:
            self._starting = None

    @classmethod
    def _local_source_for(cls, root_value, source, lines):
        root = Path(root_value).resolve()
        path, intent = _breakpoints(root, source, lines)
        local = Path(path).resolve()
        try:
            relative = local.relative_to(root)
        except ValueError:
            raise DebugError('Node attach source must be inside the workspace folder.') from None
        return local, relative, intent

    async def set_breakpoints(self, source, lines, options=None):
        if self.profile is None or self._client is None:
            raise DebugError('No active debug session.')
        local, relative, intent = await asyncio.to_thread(
            self._local_source_for, self._local_root, source, lines)
        key = str(local)
        line_options = _line_options(intent, options)
        for entry in self.verified_breakpoints.get(key, []):
            await self._client.request('Debugger.removeBreakpoint', {'breakpointId': entry['id']})
        self.verified_breakpoints[key] = []
        remote_url = (self._remote_root / PurePosixPath(relative.as_posix())).as_uri()
        entries = []
        for line in intent:
            request = {'url': remote_url, 'lineNumber': line - 1}
            condition = cdp_condition(line_options.get(line), hit_key(key, line))
            if condition:
                request['condition'] = condition
            result = await self._client.request('Debugger.setBreakpointByUrl', request)
            locations = result.get('locations', [])
            entries.append({'id': result['breakpointId'], 'verified': bool(locations),
                            'line': locations[0]['lineNumber'] + 1 if locations else line})
            self.verified_breakpoints[key] = entries
        self.requested_breakpoints[key] = intent
        self.breakpoint_options[key] = line_options
        self._emit({'event': 'breakpoints', 'body': {'path': key}})
        return entries

    def _mapped_local_source(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'file' or parsed.netloc not in {'', 'localhost'}:
            return None
        try:
            relative = PurePosixPath(unquote(parsed.path)).relative_to(self._remote_root)
        except ValueError:
            return None
        local = (self._local_root / Path(*relative.parts)).resolve()
        try:
            local.relative_to(self._local_root)
        except ValueError:
            return None
        return local

    async def stack(self):
        self._stopped()
        result = []
        for frame in self._frames:
            location = frame['location']
            url = frame.get('url') or self._scripts.get(location['scriptId'], '')
            local = await asyncio.to_thread(self._mapped_local_source, url)
            result.append({'id': frame['callFrameId'], 'name': frame['functionName'] or '(main)',
                           'line': location['lineNumber'] + 1,
                           'source': {'path': str(local)} if local else {}})
        return result

    async def _cleanup(self):
        async with self._attach_cleanup_lock:
            if self.state == 'closed':
                return
            self._state('closing')
            client = self._client
            failure = None
            if client is not None and not self._transport_lost:
                try:
                    for entries in tuple(self.verified_breakpoints.values()):
                        for entry in entries:
                            await client.request('Debugger.removeBreakpoint',
                                                 {'breakpointId': entry['id']})
                except (DebugError, OSError, TimeoutError) as error:
                    failure = f'Unable to clear Node session breakpoints: {error}'
                if failure is None and self._target_paused:
                    try:
                        await client.request('Debugger.resume')
                        self._target_paused = False
                    except (DebugError, OSError, TimeoutError) as error:
                        failure = f'Unable to resume the Node target on disconnect: {error}'
            if self._transport_lost:
                # The connection dropped during Disconnect: the Inspector already discarded
                # this session's breakpoints and resumed the target, so nothing is left over.
                failure = None
            # Closing our own connection is not a lost transport.
            self._exiting = True
            if failure is not None:
                self.disconnect_warning = failure
                self._emit({'event': 'warning', 'body': {'message': failure}})
                if self.on_output is not None:
                    self.on_output('stderr', f'Warning: {failure}\n')
            await super()._cleanup()
            self._frames = []
            self._objects = {}
            self._target_paused = False
            self._remote_root = None
            self._local_root = None
