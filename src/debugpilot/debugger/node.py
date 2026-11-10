"""Owned Node Inspector session normalized to the existing debug presentation contract."""

import asyncio
import contextlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.debugger.dap import DebugError
from debugpilot.debugger.inspector import InspectorClient
from debugpilot.debugger.python import (
    PythonDebugSession,
    _breakpoints,
    _intent,
    _line_options,
)
from debugpilot.storage.code_projects import (
    is_npm_command,
    profile_environment,
    valid_node_target,
)
from debugpilot.terminal.code_session import CodeSession, command_argv

_GRAMMAR = (
    'Supported Node commands: node server.js [args...] (also .cjs/.mjs), without runtime flags. '
    'For npm run dev, add nodeDebug: ["node", "server.js", "args..."] to the same profile. '
    'F5 keeps the original command. No run-mode fallback.'
)
_ANSI = re.compile(r'\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]')
_ENDPOINT = re.compile(r'^Debugger listening on (ws://127\.0\.0\.1:[1-9]\d*/[\da-f-]{36})$')


def _js_template(message):
    """A JS template literal for a logpoint.

    A balanced {expr} is interpolated, so it may contain braces such as an object literal.
    An empty {} or an unclosed brace stays literal text: either would otherwise make the
    condition throw, and Node would then neither log nor report anything.
    """
    parts, literal, index = [], [], 0
    while index < len(message):
        if message[index] == '{':
            end = _closing_brace(message, index)
            if end is not None and message[index + 1:end].strip():
                parts.append(_js_literal(''.join(literal)))
                literal = []
                parts.append(f'${{({message[index + 1:end]})}}')
                index = end + 1
                continue
        literal.append(message[index])
        index += 1
    parts.append(_js_literal(''.join(literal)))
    return '`' + ''.join(parts) + '`'


def _closing_brace(text, start):
    depth = 0
    for index in range(start, len(text)):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth == 0:
                return index
    return None


def _js_literal(text):
    return text.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$')


def cdp_condition(options):
    """CDP has no logpoints: log through the condition and return false, like VS Code."""
    if options is None:
        return ''
    if not options.log_message:
        return options.condition or ''
    log = f'console.log({_js_template(options.log_message)}), false'
    return f'({options.condition}) && ({log})' if options.condition else log


_FUNCTION_NAME = re.compile(r'(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)?')


def _display(value):
    """CDP RemoteObject as shown in variables and watches; functions by name, not source."""
    if value.get('type') == 'function':
        description = (value.get('description') or '').lstrip()
        if description.startswith('class'):
            return description.split('{', 1)[0].strip()
        match = _FUNCTION_NAME.match(description)
        return f"ƒ {(match.group(1) if match else None) or 'anonymous'}()"
    return value.get('unserializableValue', value.get('description',
                     json.dumps(value.get('value', None))))


def _source(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'file' or parsed.netloc not in {'', 'localhost'}:
        return None
    return str(Path(url2pathname(unquote(parsed.path))))


class NodeDebugSession(PythonDebugSession):
    """Reuse Python's UI events and idempotent owned CodeSession cleanup, not its DAP wire."""

    def __init__(self, on_event=None, on_output=None, *, timeout=15):
        super().__init__(on_event, on_output, timeout=timeout)
        self._endpoint = asyncio.Event()
        self._paused = asyncio.Event()
        self._url = None
        self._initial = True
        self._frames = []
        self._scripts = {}
        self._objects = {}
        self._buffer = ''
        self._disconnect_task = None
        self._exiting = False

    def _output(self, text):
        self._buffer += text
        # ConPTY may split escape sequences; clean only complete lines.
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            self._line(_ANSI.sub('', line).replace('\r', ''))
        if len(self._buffer) > 65536:
            self._line(_ANSI.sub('', self._buffer[:65536]))
            self._buffer = self._buffer[65536:]

    def _line(self, line):
        match = _ENDPOINT.fullmatch(line)
        if match and self._url is None:
            self._url = match[1]
            self._endpoint.set()
        elif line.endswith('Waiting for the debugger to disconnect...'):
            prefix = line.removesuffix('Waiting for the debugger to disconnect...')
            if prefix and self.on_output:
                self.on_output('stdout', prefix)
            # Node waits here on normal exit. Disconnect without killing the process;
            # CodeSession then drains output and publishes the actual exit status.
            self._exiting = True
            if self._client is not None and self._disconnect_task is None:
                self._disconnect_task = asyncio.create_task(self._client.close())
        elif (line.startswith('For help, see: https://nodejs.org/')
              or line in {'Debugger attached.', 'Debugger ending on ' + str(self._url)}):
            pass
        elif self.on_output:
            # The owned PTY merges stdout/stderr; expose that explicitly as console.
            self.on_output('stdout', line + '\n')

    def _process_exit(self):
        if self._buffer:
            text, self._buffer = self._buffer, ''
            if self.on_output:
                self.on_output('stdout', _ANSI.sub('', text).replace('\r', ''))
        if self.state not in {'closing', 'closed'}:
            self.exit_code = self._adapter.exit_code
            self._emit({'event': 'exited', 'body': {'exitCode': self.exit_code}})
            self._event({'event': 'terminated', 'body': {}})
            self._endpoint.set()

    def _cdp_event(self, message):
        method, params = message.get('method'), message.get('params', {})
        if method == 'Debugger.scriptParsed':
            self._scripts[params['scriptId']] = params.get('url', '')
        elif method == 'Debugger.paused':
            self._frames = params.get('callFrames', [])[:100]
            self._objects = {}
            self._paused.set()
            if not self._initial:
                self._event({'event': 'stopped', 'body': {'threadId': 1}})
        elif method == 'Debugger.resumed':
            self._frames = []
            self._objects = {}
            self._event({'event': 'continued', 'body': {}})
        elif method == 'Debugger.breakpointResolved':
            for entries in self.verified_breakpoints.values():
                for entry in entries:
                    if entry['id'] == params['breakpointId']:
                        entry.update(verified=True, line=params['location']['lineNumber'] + 1)
            self._emit({'event': 'breakpoints', 'body': {}})
        elif method == 'transportClosed' and not self._exiting:
            self._event({'event': 'transportClosed', 'body': params})

    async def start(self, profile, breakpoints, options=None):
        if self.state not in {'idle', 'closed'}:
            raise DebugError('A debug session is already active; Stop before starting again.')
        command = profile.command
        if is_npm_command(command):
            command = profile.node_debug
        if not valid_node_target(command):
            raise DebugError(_GRAMMAR)
        try:
            # Node runs as our own process, so it takes the full environment directly.
            environment = profile_environment(profile)
        except ConfigurationError as error:
            raise DebugError(str(error)) from None
        intent, start_options = _intent(profile.root, breakpoints, options)
        try:
            argv = command_argv(tuple(command))
        except RuntimeError as error:
            raise DebugError(
                f'{error}. Select an installed Node runtime. No run-mode fallback.') from error
        target = (profile.root / command[1]).resolve()
        self.profile = profile
        self.requested_breakpoints = intent
        self.verified_breakpoints = {}
        self.breakpoint_options = {}
        self.exit_code = None
        self.thread_id = None
        self.events = asyncio.Queue()
        self._endpoint.clear()
        self._paused.clear()
        self._url = None
        self._initial = True
        self._scripts = {}
        self._buffer = ''
        self._exiting = False
        self._disconnect_task = None
        self._starting = asyncio.current_task()
        self._state('starting')
        try:
            async with asyncio.timeout(self.timeout):
                self._adapter = CodeSession(self._output, self._process_exit)
                await self._adapter.open_command(
                    (argv[0], '--inspect-brk=127.0.0.1:0', str(target), *argv[2:]), profile.root,
                    env=environment)
                self._emit({'event': 'adapterStarted', 'body': {}})
                await self._endpoint.wait()
                if self._url is None:
                    raise DebugError(
                        'Node Inspector did not start. Check the selected runtime and script.')
                self._client = await InspectorClient.connect(
                    self._url, self._cdp_event, timeout=self.timeout)
                await self._client.request('Runtime.enable')
                await self._client.request('Debugger.enable')
                for path, lines in intent.items():
                    await self.set_breakpoints(path, lines, start_options.get(path))
                await self._client.request('Runtime.runIfWaitingForDebugger')
                await self._paused.wait()
                identity = await self._client.request('Runtime.evaluate', {
                    'expression': 'JSON.stringify([process.argv[1], process.execArgv])',
                    'returnByValue': True,
                })
                value = identity.get('result', {}).get('value')
                owned = json.loads(value) if isinstance(value, str) else None
                if (not owned or await asyncio.to_thread(Path(owned[0]).resolve) != target
                        or '--inspect-brk=127.0.0.1:0' not in owned[1]):
                    raise DebugError('Inspector target does not match the owned Node launch.')
                self._initial = False
                # Hide the startup pause unless the user actually requested that location.
                frame = self._frames[0] if self._frames else {}
                location = frame.get('location', {})
                path = _source(self._scripts.get(location.get('scriptId'), ''))
                if location.get('lineNumber', -1) + 1 in intent.get(path, ()):
                    self._event({'event': 'stopped', 'body': {'threadId': 1}})
                else:
                    self._state('running')
                    await self._client.request('Debugger.resume')
        except BaseException as error:
            await self._cleanup()
            if isinstance(error, TimeoutError):
                raise DebugError('Node Inspector startup timed out. Check the Node runtime; '
                                 'no run-mode fallback.') from None
            if isinstance(error, (OSError, ValueError)):
                raise DebugError(f'Unable to debug Node: {error}') from error
            raise
        finally:
            self._starting = None

    async def set_breakpoints(self, source, lines, options=None):
        if self.profile is None or self._client is None:
            raise DebugError('No active debug session.')
        path, intent = _breakpoints(self.profile.root, source, lines)
        line_options = _line_options(intent, options)
        previous = self.verified_breakpoints.get(path, [])
        for entry in previous:
            await self._client.request('Debugger.removeBreakpoint', {'breakpointId': entry['id']})
        entries = []
        source_url = (await asyncio.to_thread(Path(path).resolve)).as_uri()
        for line in intent:
            request = {'url': source_url, 'lineNumber': line - 1}
            condition = cdp_condition(line_options.get(line))
            if condition:
                request['condition'] = condition
            result = await self._client.request('Debugger.setBreakpointByUrl', request)
            locations = result.get('locations', [])
            entries.append({'id': result['breakpointId'], 'verified': bool(locations),
                            'line': locations[0]['lineNumber'] + 1 if locations else line})
        self.requested_breakpoints[path] = intent
        self.breakpoint_options[path] = line_options
        self.verified_breakpoints[path] = entries
        self._emit({'event': 'breakpoints', 'body': {'path': path}})
        return entries

    async def stack(self):
        self._stopped()
        result = []
        for frame in self._frames:
            location = frame['location']
            path = _source(frame.get('url') or self._scripts.get(location['scriptId'], ''))
            result.append({'id': frame['callFrameId'], 'name': frame['functionName'] or '(main)',
                           'line': location['lineNumber'] + 1,
                           'source': {'path': path} if path else {}})
        return result

    def _reference(self, object_id):
        if not object_id:
            return 0
        reference = len(self._objects) + 1
        self._objects[reference] = object_id
        return reference

    async def scopes(self, frame_id):
        self._stopped()
        frame = next((f for f in self._frames if f['callFrameId'] == frame_id), None)
        if frame is None:
            raise DebugError('Frame is no longer paused.')
        return [{'name': s.get('name') or s['type'], 'expensive': s['type'] == 'global',
                 'variablesReference': self._reference(s['object'].get('objectId'))}
                for s in frame['scopeChain']]

    async def variables(self, reference):
        self._stopped()
        if reference not in self._objects:
            raise DebugError('Variables are no longer paused.')
        result = await self._client.request('Runtime.getProperties', {
            'objectId': self._objects[reference], 'ownProperties': True,
            'generatePreview': False,
        })
        values = []
        for prop in result.get('result', [])[:200]:
            value = prop.get('value')  # Do not invoke getters or evaluate expressions.
            if value is not None:
                values.append({'name': prop['name'], 'value': _display(value),
                               'variablesReference': self._reference(value.get('objectId'))})
        return values

    async def evaluate(self, expression, frame_id):
        """Evaluate a watch expression in a paused call frame; exceptions become errors."""
        self._stopped()
        if not any(frame['callFrameId'] == frame_id for frame in self._frames):
            raise DebugError('Frame is no longer paused.')
        result = await self._client.request('Debugger.evaluateOnCallFrame', {
            'callFrameId': frame_id, 'expression': expression, 'generatePreview': False,
        })
        details = result.get('exceptionDetails')
        if details is not None:
            message = (details.get('exception', {}).get('description')
                       or details.get('text') or 'Evaluation failed.')
            raise DebugError(message.splitlines()[0])
        return _display(result.get('result', {}))

    async def _resume(self, command):
        self._stopped()
        self.thread_id = None
        self._state('running')
        self._paused.clear()
        # A failed resume is uncertain: never pretend an old frame is still valid.
        methods = {'continue': 'Debugger.resume', 'next': 'Debugger.stepOver',
                   'stepIn': 'Debugger.stepInto', 'stepOut': 'Debugger.stepOut'}
        return await self._client.request(methods[command])

    async def close(self):
        await super().close()
        if self._disconnect_task is not None:
            with contextlib.suppress(DebugError, OSError):
                await self._disconnect_task
