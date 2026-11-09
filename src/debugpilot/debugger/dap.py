"""Bounded DAP framing over a private loopback stream, never over the PTY."""

import asyncio
import contextlib
import json


class DebugError(RuntimeError):
    """Debug startup, protocol, or adapter error; never a request to run normally."""

    # The adapter's detailed text for a failed response, such as Delve's build output.
    detail: str | None = None


def _response_error(message):
    error = DebugError(message.get('message', 'DAP failure'))
    body = message.get('body')
    failure = body.get('error') if isinstance(body, dict) else None
    detail = failure.get('format') if isinstance(failure, dict) else None
    if isinstance(detail, str) and detail.strip():
        error.detail = detail.strip()
    return error


# Sentinel: use the client's own timeout. None is a valid explicit value (no deadline).
_CLIENT_TIMEOUT = object()


class DAPClient:
    def __init__(self, reader, writer, on_event, *, timeout=15):
        self.reader, self.writer = reader, writer
        self.on_event = on_event
        self.timeout = timeout
        self._sequence = 0
        self._pending = {}
        self._closed = False
        self._task = asyncio.create_task(self._read())

    async def _send(self, message):
        if self._closed:
            raise DebugError('Debug adapter connection is closed.')
        self._sequence += 1
        message = {**message, 'seq': self._sequence}
        data = json.dumps(message).encode('utf-8')
        self.writer.write(f'Content-Length: {len(data)}\r\n\r\n'.encode() + data)
        await self.writer.drain()
        return self._sequence

    async def request(self, command, arguments=None, *, deadline=_CLIENT_TIMEOUT):
        """Send one request; ``deadline=None`` waits with no limit (for example a build)."""
        # Register before sending; a response can arrive during drain().
        sequence = self._sequence + 1
        future = asyncio.get_running_loop().create_future()
        self._pending[sequence] = future
        try:
            async with asyncio.timeout(self.timeout if deadline is _CLIENT_TIMEOUT else deadline):
                await self._send({'type': 'request', 'command': command,
                                  'arguments': arguments or {}})
                return await future
        except TimeoutError:
            raise DebugError(f'Debug adapter timed out: {command}.') from None
        except (OSError, ConnectionError) as error:
            raise DebugError(f'Debug adapter connection failed: {error}') from error
        finally:
            self._pending.pop(sequence, None)
            if not future.done():
                future.cancel()

    async def _read(self):
        reason = 'Debug adapter disconnected.'
        try:
            while True:
                header = await self.reader.readuntil(b'\r\n\r\n')
                fields = dict(line.split(b':', 1) for line in header.strip().split(b'\r\n'))
                length = int(fields[b'Content-Length'].strip())
                if not 0 < length <= 8 * 1024 * 1024:
                    raise ValueError('DAP message exceeds the 8 MiB limit')
                message = json.loads(await self.reader.readexactly(length))
                if message['type'] == 'response':
                    future = self._pending.get(message['request_seq'])
                    if future and not future.done():
                        if message.get('success'):
                            future.set_result(message.get('body', {}))
                        else:
                            future.set_exception(_response_error(message))
                elif message['type'] == 'event':
                    self.on_event(message)
                elif message['type'] == 'request':
                    # No shell, terminal launcher, or client-side executable capability.
                    await self._send({'type': 'response', 'request_seq': message['seq'],
                                      'command': message['command'], 'success': False,
                                      'message': 'Client reverse requests are unsupported.'})
        except asyncio.CancelledError:
            pass
        except (OSError, ValueError, KeyError, TypeError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError) as error:
            reason = f'Debug adapter disconnected: {error}'
        finally:
            self._closed = True
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(DebugError(reason))
            self.on_event({'event': 'transportClosed', 'body': {'message': reason}})

    async def close(self):
        self._closed = True
        self.writer.close()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        with contextlib.suppress(OSError, TimeoutError):
            await asyncio.wait_for(self.writer.wait_closed(), 1)
