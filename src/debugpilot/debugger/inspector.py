"""Small bounded RFC6455/CDP client for an owned loopback Node inspector only."""

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import struct
from urllib.parse import urlsplit

from debugpilot.debugger.dap import DebugError

_LIMIT = 8 * 1024 * 1024


class InspectorClient:
    def __init__(self, reader, writer, on_event, timeout):
        self.reader, self.writer = reader, writer
        self.on_event, self.timeout = on_event, timeout
        self._sequence = 0
        self._pending = {}
        self._closed = False
        self._task = asyncio.create_task(self._read())

    @classmethod
    async def connect(cls, endpoint, on_event, *, timeout=15):  # noqa: ASYNC109
        # The handshake and subsequent requests each enforce this explicit deadline.
        try:
            url = urlsplit(endpoint)
            if (url.scheme != 'ws' or url.hostname != '127.0.0.1'
                    or not url.port or url.username or url.password or url.query or url.fragment
                    or not url.path.startswith('/') or len(url.path) > 256
                    or any(ord(c) < 33 or ord(c) > 126 for c in url.path)):
                raise ValueError
        except ValueError:
            raise DebugError(
                'Inspector requires an unambiguous loopback WebSocket endpoint.') from None
        writer = None
        connected = False
        try:
            async with asyncio.timeout(timeout):
                reader, writer = await asyncio.open_connection('127.0.0.1', url.port, limit=8192)
                key = base64.b64encode(os.urandom(16))
                writer.write(
                    f'GET {url.path} HTTP/1.1\r\nHost: 127.0.0.1:{url.port}\r\n'.encode()
                    + b'Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\n'
                    + b'Sec-WebSocket-Key: ' + key + b'\r\n\r\n')
                await writer.drain()
                header = await reader.readuntil(b'\r\n\r\n')
                lines = header.split(b'\r\n')
                fields = {k.lower(): v.strip() for k, v in
                          (line.split(b':', 1) for line in lines[1:] if line)}
                accept = base64.b64encode(hashlib.sha1(
                    key + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                if (lines[0] != b'HTTP/1.1 101 Switching Protocols'
                        or fields.get(b'upgrade', b'').lower() != b'websocket'
                        or b'upgrade' not in fields.get(b'connection', b'').lower().split(b', ')
                        or fields.get(b'sec-websocket-accept') != accept
                        or b'sec-websocket-extensions' in fields):
                    raise ValueError('invalid WebSocket handshake')
                connected = True
                return cls(reader, writer, on_event, timeout)
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError) as error:
            raise DebugError(f'Unable to connect to Node Inspector: {error}') from error
        finally:
            # Ownership transfers only after a successful handshake.
            if writer is not None and not connected:
                writer.close()

    async def _send(self, opcode, data):
        if self._closed:
            raise DebugError('Inspector connection is closed.')
        if len(data) > _LIMIT:
            raise DebugError('Inspector message exceeds 8 MiB.')
        mask = os.urandom(4)
        length = len(data)
        header = bytes([128 | opcode])
        if length < 126:
            header += bytes([128 | length])
        elif length <= 65535:
            header += bytes([128 | 126]) + struct.pack('!H', length)
        else:
            header += bytes([128 | 127]) + struct.pack('!Q', length)
        self.writer.write(header + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(data)))
        await self.writer.drain()

    async def request(self, method, params=None):
        self._sequence += 1
        sequence = self._sequence
        future = asyncio.get_running_loop().create_future()
        self._pending[sequence] = future
        try:
            async with asyncio.timeout(self.timeout):
                await self._send(1, json.dumps({'id': sequence, 'method': method,
                                               'params': params or {}}).encode())
                return await future
        except TimeoutError:
            raise DebugError(f'Inspector timed out: {method}.') from None
        except OSError as error:
            raise DebugError(f'Inspector request failed: {error}') from error
        finally:
            self._pending.pop(sequence, None)
            if not future.done():
                future.cancel()

    async def _read(self):
        reason = 'Inspector disconnected.'
        fragments = bytearray()
        fragmented = False
        try:
            while True:
                first, second = await self.reader.readexactly(2)
                final, opcode = bool(first & 128), first & 15
                if first & 112 or second & 128:
                    raise ValueError('extensions and masked server frames are unsupported')
                length = second & 127
                if length == 126:
                    length = struct.unpack('!H', await self.reader.readexactly(2))[0]
                elif length == 127:
                    length = struct.unpack('!Q', await self.reader.readexactly(8))[0]
                if length > _LIMIT or len(fragments) + length > _LIMIT:
                    raise ValueError('Inspector message exceeds 8 MiB')
                if opcode >= 8 and (not final or length > 125):
                    raise ValueError('invalid control frame')
                # Even a peer which stalls midway through a frame has a bounded lifetime.
                async with asyncio.timeout(self.timeout):
                    data = await self.reader.readexactly(length)
                if opcode == 8:
                    break
                if opcode == 9:
                    await self._send(10, data)
                    continue
                if opcode == 10:
                    continue
                if opcode == 1 and not fragmented:
                    fragments = bytearray(data)
                elif opcode == 0 and fragmented:
                    fragments.extend(data)
                else:
                    raise ValueError('unsupported frame or invalid fragmentation')
                fragmented = not final
                if not final:
                    continue
                message = json.loads(fragments.decode('utf-8'))
                fragments.clear()
                if not isinstance(message, dict):
                    raise ValueError('invalid CDP message')
                if 'id' in message:
                    future = self._pending.get(message['id'])
                    if future is not None and not future.done():
                        if 'error' in message:
                            future.set_exception(DebugError(str(message['error'])))
                        else:
                            future.set_result(message.get('result', {}))
                elif 'method' in message:
                    self.on_event(message)
        except asyncio.CancelledError:
            pass
        except (OSError, ValueError, KeyError, TypeError, TimeoutError,
                asyncio.IncompleteReadError) as error:
            reason = f'Inspector disconnected: {error}'
        finally:
            self._closed = True
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(DebugError(reason))
            self.on_event({'method': 'transportClosed', 'params': {'message': reason}})

    async def close(self):
        self._closed = True
        self.writer.close()
        if self._task is not asyncio.current_task():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        with contextlib.suppress(OSError, TimeoutError):
            await asyncio.wait_for(self.writer.wait_closed(), 1)
