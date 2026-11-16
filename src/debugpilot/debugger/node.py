"""Owned Node Inspector session normalized to the existing debug presentation contract."""

import asyncio
import contextlib
import itertools
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
from debugpilot.debugger.source_maps import SourceMapIndex
from debugpilot.debugger.terminal_lines import TerminalLines
from debugpilot.storage.code_projects import (
    is_npm_command,
    profile_environment,
    valid_node_target,
)
from debugpilot.terminal.code_session import CodeSession, command_argv

_GRAMMAR = (
    'Supported Node commands: node server.js [args...] (also .cjs/.mjs, and .ts/.cts/.mts '
    'on Node 22.18+), without runtime flags. '
    'For npm run dev, add nodeDebug: ["node", "server.js", "args..."] to the same profile. '
    'F5 keeps the original command. No run-mode fallback.'
)
_TYPESCRIPT = frozenset({'.ts', '.cts', '.mts'})
# A JavaScript name that can be assigned to, for scopes V8 cannot set directly.
_IDENTIFIER = re.compile(r'[A-Za-z_$][\w$]*')
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


# One counter key per breakpoint registration, so setting breakpoints again restarts counting.
_HIT_KEYS = itertools.count(1)


def _hit_test(hit_condition, key):
    """CDP has no hit counts: count in a page global keyed per breakpoint, like VS Code."""
    match = re.fullmatch(r'(==|>=|<=|>|<|%)?(\d+)', hit_condition)
    operator, count = match.group(1) or '==', match.group(2)
    name = json.dumps(key)
    hits = (f'((globalThis.__debugealoHits ??= {{}})[{name}] = '
            f'(globalThis.__debugealoHits[{name}] || 0) + 1)')
    if operator == '%':
        return f'{hits} % {count} === 0'
    return f'{hits} {"===" if operator == "==" else operator} {count}'


def cdp_condition(options, key=''):
    """CDP has no logpoints: log through the condition and return false, like VS Code."""
    if options is None:
        return ''
    test = options.condition
    if options.hit_condition:
        test = _hit_test(options.hit_condition, key)
    if not options.log_message:
        return test or ''
    log = f'console.log({_js_template(options.log_message)}), false'
    return f'({test}) && ({log})' if test else log


def hit_key(path, line):
    """A fresh counter key for one breakpoint line."""
    return f'{path}:{line}:{next(_HIT_KEYS)}'


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


def _node_argv(profile, command, environment=None):
    """Resolve the Node runtime on the profile's PATH, as Run does."""
    if environment is None:
        try:
            environment = profile_environment(profile)
        except ConfigurationError as error:
            raise DebugError(str(error)) from None
    try:
        return command_argv(tuple(command), environment)
    except RuntimeError as error:
        raise DebugError(
            f'{error}. Select an installed Node runtime. No run-mode fallback.') from error


def _source(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'file' or parsed.netloc not in {'', 'localhost'}:
        return None
    return str(Path(url2pathname(unquote(parsed.path))))


def _call_argument(result):
    """The CDP CallArgument that passes an evaluated RemoteObject on."""
    if 'objectId' in result:
        return {'objectId': result['objectId']}
    if 'unserializableValue' in result:
        return {'unserializableValue': result['unserializableValue']}
    if result.get('type') == 'undefined':
        return {}
    return {'value': result.get('value')}


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
        # Scope reference -> (call frame, scope number, scope type) for set_variable.
        self._scopes = {}
        self._changed = {}
        self._lines = TerminalLines(self._line, self._partial_output)
        self._disconnect_task = None
        self._exiting = False
        self._source_maps = None

    def _output(self, text):
        self._lines.feed(text)

    def _partial_output(self, text):
        if self.on_output:
            self.on_output('stdout', text)

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
        self._lines.finish()
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
            self._scopes = {}
            self._changed = {}
            self._paused.set()
            if not self._initial:
                self._event({'event': 'stopped', 'body': {'threadId': 1}})
        elif method == 'Debugger.resumed':
            self._frames = []
            self._objects = {}
            self._scopes = {}
            self._changed = {}
            self._event({'event': 'continued', 'body': {}})
        elif method == 'Debugger.breakpointResolved':
            for entries in self.verified_breakpoints.values():
                for entry in entries:
                    if entry['id'] is not None and entry['id'] == params['breakpointId']:
                        entry.update(verified=True,
                                     line=self._original_location(params['location'])[1])
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
        argv = _node_argv(profile, command, environment)
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
        self._lines.reset()
        self._exiting = False
        self._disconnect_task = None
        self._starting = asyncio.current_task()
        self._state('starting')
        try:
            async with asyncio.timeout(self.timeout):
                # Read before the first breakpoint: compiled files bind before they load.
                # A .ts launch runs its sources directly, so a build's maps never apply.
                self._source_maps = None if target.suffix.lower() in _TYPESCRIPT else (
                    await asyncio.to_thread(SourceMapIndex, profile.root))
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
                path, line = self._original_location(location) if location else (None, 0)
                if line in intent.get(path, ()):
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

    def input_echo(self):
        # Node runs in the PTY itself, so the terminal's own echo is already in its output.
        return False

    async def set_breakpoints(self, source, lines, options=None):
        if self.profile is None or self._client is None:
            raise DebugError('No active debug session.')
        path, intent = _breakpoints(self.profile.root, source, lines)
        line_options = _line_options(intent, options)
        entries = await self._bind_breakpoints(path, Path(path), intent, line_options)
        self.requested_breakpoints[path] = intent
        self.breakpoint_options[path] = line_options
        self._emit({'event': 'breakpoints', 'body': {'path': path}})
        return entries

    def _script_url(self, path):
        """The Inspector URL of a local script."""
        return Path(path).resolve().as_uri()

    def _local_script(self, url):
        """The local file of an Inspector script URL, or None."""
        path = _source(url)
        return Path(path) if path else None

    def _generated_target(self, path, line):
        """(url, 0-based line, column or None) to set for a local line; None when unmapped.

        A source that compiled files map back to is set on the generated line instead.
        """
        maps = self._source_maps
        if maps is not None and maps.maps(path):
            position = maps.generated_position(path, line)
            if position is None:
                return None
            generated, generated_line, column = position
            url = self._script_url(generated)
            return (url, generated_line - 1, column) if url else None
        url = self._script_url(path)
        return (url, line - 1, None) if url else None

    def _original_location(self, location, url=None):
        """(local path or None, 1-based line) of an Inspector location, through source maps."""
        url = url or self._scripts.get(location.get('scriptId'), '')
        line = location.get('lineNumber', -1) + 1
        local = self._local_script(url)
        if local is not None and self._source_maps is not None:
            mapped = self._source_maps.original_position(
                local, line, location.get('columnNumber', 0))
            if mapped is not None:
                return str(mapped[0]), mapped[1]
        return (str(local) if local else None), line

    async def _bind_breakpoints(self, key, path, intent, line_options):
        for entry in self.verified_breakpoints.get(key, []):
            if entry['id'] is not None:
                await self._client.request(
                    'Debugger.removeBreakpoint', {'breakpointId': entry['id']})
        self.verified_breakpoints[key] = entries = []
        for line in intent:
            target = await asyncio.to_thread(self._generated_target, path, line)
            if target is None:
                # A mapped source line with no generated code never binds.
                entries.append({'id': None, 'verified': False, 'line': line})
                continue
            url, generated_line, column = target
            request = {'url': url, 'lineNumber': generated_line}
            if column is not None:
                request['columnNumber'] = column
            condition = cdp_condition(line_options.get(line), hit_key(key, line))
            if condition:
                request['condition'] = condition
            result = await self._client.request('Debugger.setBreakpointByUrl', request)
            locations = result.get('locations', [])
            resolved = (await asyncio.to_thread(self._original_location, locations[0], url))[1] \
                if locations else line
            entries.append({'id': result['breakpointId'], 'verified': bool(locations),
                            'line': resolved})
        return entries

    async def stack(self):
        self._stopped()
        result = []
        for frame in self._frames:
            location = frame['location']
            path, line = await asyncio.to_thread(
                self._original_location, location, frame.get('url'))
            result.append({'id': frame['callFrameId'], 'name': frame['functionName'] or '(main)',
                           'line': line, 'source': {'path': path} if path else {}})
        return result

    def _reference(self, object_id, frame_id):
        """A variables reference for a remote object seen from a paused call frame."""
        if not object_id:
            return 0
        reference = len(self._objects) + 1
        self._objects[reference] = (object_id, frame_id)
        return reference

    async def scopes(self, frame_id):
        self._stopped()
        frame = next((f for f in self._frames if f['callFrameId'] == frame_id), None)
        if frame is None:
            raise DebugError('Frame is no longer paused.')
        scopes = []
        for number, scope in enumerate(frame['scopeChain']):
            reference = self._reference(scope['object'].get('objectId'), frame_id)
            self._scopes[reference] = (frame_id, number, scope['type'])
            scopes.append({'name': scope.get('name') or scope['type'],
                           'expensive': scope['type'] == 'global',
                           'variablesReference': reference})
        return scopes

    async def set_variable(self, reference, name, value):
        """Set a variable of a paused scope to a value expression; returns its new value."""
        self._stopped()
        if reference not in self._objects:
            raise DebugError('Variables are no longer paused.')
        if reference not in self._scopes:
            return await self._set_property(reference, name, value)
        frame_id, number, kind = self._scopes[reference]
        if kind in {'local', 'closure', 'catch'}:
            result = await self._evaluate_on(frame_id, value)
            await self._client.request('Debugger.setVariableValue', {
                'scopeNumber': number, 'variableName': name,
                'newValue': _call_argument(result), 'callFrameId': frame_id,
            })
        else:
            # V8 sets only local, closure and catch scopes; assign the others (block,
            # script, module) in the frame, where the name resolves to that variable.
            if not _IDENTIFIER.fullmatch(name):
                raise DebugError(f'{name} cannot be set.')
            result = await self._evaluate_on(frame_id, f'{name} = ({value})')
        # V8's scope objects are copies taken at the pause, so remember the new value.
        self._changed[(frame_id, number, name)] = result
        return _display(result)

    async def full_value(self, expression, reference, frame_id):
        """An object's whole value as indented JSON, or None (primitives, cycles, functions)."""
        self._stopped()
        if reference not in self._objects:
            return None
        response = await self._client.request('Runtime.callFunctionOn', {
            'objectId': self._objects[reference][0], 'returnByValue': True,
            'functionDeclaration': 'function () { return JSON.stringify(this, null, 2); }',
        })
        value = response.get('result', {}).get('value')
        if response.get('exceptionDetails') is not None or not isinstance(value, str):
            return None
        return value

    async def _set_property(self, reference, name, value):
        """Set a field of an object; objects are live, so no overlay is needed."""
        object_id, frame_id = self._objects[reference]
        result = await self._evaluate_on(frame_id, value)
        response = await self._client.request('Runtime.callFunctionOn', {
            'objectId': object_id,
            'functionDeclaration': "function (name, value) { 'use strict'; this[name] = value; }",
            'arguments': [{'value': name}, _call_argument(result)],
        })
        details = response.get('exceptionDetails')
        if details is not None:
            message = (details.get('exception', {}).get('description')
                       or details.get('text') or f'{name} cannot be set.')
            raise DebugError(message.splitlines()[0])
        return _display(result)

    async def _evaluate_on(self, frame_id, expression):
        response = await self._client.request('Debugger.evaluateOnCallFrame', {
            'callFrameId': frame_id, 'expression': expression, 'generatePreview': False,
        })
        details = response.get('exceptionDetails')
        if details is not None:
            message = (details.get('exception', {}).get('description')
                       or details.get('text') or 'Evaluation failed.')
            raise DebugError(message.splitlines()[0])
        return response.get('result', {})

    async def variables(self, reference):
        self._stopped()
        if reference not in self._objects:
            raise DebugError('Variables are no longer paused.')
        result = await self._client.request('Runtime.getProperties', {
            'objectId': self._objects[reference][0], 'ownProperties': True,
            'generatePreview': False,
        })
        values = []
        frame_id = self._objects[reference][1]
        _, number, _ = self._scopes.get(reference, (None, None, None))
        for prop in result.get('result', [])[:200]:
            value = self._changed.get((frame_id, number, prop['name']), prop.get('value'))
            # Do not invoke getters or evaluate expressions.
            if value is not None:
                values.append({'name': prop['name'], 'value': _display(value),
                               'variablesReference': self._reference(
                                   value.get('objectId'), frame_id)})
        return values

    async def evaluate(self, expression, frame_id):
        """Evaluate a watch expression in a paused call frame; exceptions become errors."""
        return (await self.inspect(expression, frame_id))['value']

    async def inspect(self, expression, frame_id):
        """A watch's value, and the variables reference of its fields (0 when it has none)."""
        self._stopped()
        if not any(frame['callFrameId'] == frame_id for frame in self._frames):
            raise DebugError('Frame is no longer paused.')
        result = await self._evaluate_on(frame_id, expression)
        return {'value': _display(result),
                'variablesReference': self._reference(result.get('objectId'), frame_id)}

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
