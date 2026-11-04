"""Bounded RFC6455 subset used only for the local Node inspector."""
import asyncio
import base64
import hashlib
import json
import struct

import pytest

from debugpilot.debugger.dap import DebugError
from debugpilot.debugger.inspector import InspectorClient


async def frame(reader):
    first, second = await reader.readexactly(2)
    length = second & 127
    if length == 126:
        length = struct.unpack('!H', await reader.readexactly(2))[0]
    mask = await reader.readexactly(4)
    data = await reader.readexactly(length)
    return first & 15, bytes(v ^ mask[i % 4] for i, v in enumerate(data))


async def handshake(reader, writer):
    header = await reader.readuntil(b'\r\n\r\n')
    key = next(line.split(b': ', 1)[1] for line in header.split(b'\r\n')
               if line.startswith(b'Sec-WebSocket-Key:'))
    accept = base64.b64encode(hashlib.sha1(
        key + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
    writer.write(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                 b'Connection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
    await writer.drain()


def packet(opcode, data, final=True):
    return bytes([(128 if final else 0) | opcode, len(data)]) + data


async def test_request_fragmentation_ping_event_and_disconnect():
    done = asyncio.Event()
    async def serve(reader, writer):
        try:
            await handshake(reader, writer)
            opcode, data = await frame(reader)
            assert opcode == 1
            request = json.loads(data)
            assert request['method'] == 'Runtime.enable'
            response = json.dumps({'id': request['id'], 'result': {'ok': True}}).encode()
            writer.write(packet(1, response[:8], False) + packet(9, b'ping')
                         + packet(0, response[8:]) + packet(1, b'{"method":"paused"}'))
            await writer.drain()
            assert await frame(reader) == (10, b'ping')
            await reader.read()
        finally:
            writer.close()
            done.set()
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    messages = []
    received = asyncio.Event()

    def receive(message):
        messages.append(message)
        received.set()

    client = None
    try:
        port = server.sockets[0].getsockname()[1]
        client = await InspectorClient.connect(f'ws://127.0.0.1:{port}/owned', receive)
        assert await client.request('Runtime.enable') == {'ok': True}
        async with asyncio.timeout(2):
            await received.wait()
        assert messages[0] == {'method': 'paused'}
    finally:
        if client:
            await client.close()
            await client.close()
        server.close()
        await server.wait_closed()
        await asyncio.wait_for(done.wait(), 2)


@pytest.mark.parametrize('url', ['ws://example.com:9229/id', 'ws://localhost:9229/id',
    'ws://127.0.0.1:0/id', 'wss://127.0.0.1:9229/id',
    'ws://user@127.0.0.1:9229/id', 'ws://127.0.0.1:9229/id?query'])
async def test_reject_non_loopback_or_ambiguous_endpoint(url):
    with pytest.raises(DebugError, match='loopback'):
        await InspectorClient.connect(url, lambda m: None)


@pytest.mark.parametrize('bad', [b'\x81\x7f' + struct.pack('!Q', 8 * 1024 * 1024 + 1),
                                b'\xc1\x00', b'\x82\x00'])
async def test_oversized_or_unsupported_frames_fail_pending_request(bad):
    done = asyncio.Event()
    async def serve(reader, writer):
        try:
            await handshake(reader, writer)
            await frame(reader)
            writer.write(bad)
            await writer.drain()
            await reader.read()
        finally:
            writer.close()
            done.set()
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    client = None
    try:
        port = server.sockets[0].getsockname()[1]
        client = await InspectorClient.connect(f'ws://127.0.0.1:{port}/owned', lambda m: None)
        with pytest.raises(DebugError, match='Inspector disconnected'):
            await client.request('Runtime.enable')
    finally:
        if client:
            await client.close()
        server.close()
        await server.wait_closed()
        await asyncio.wait_for(done.wait(), 2)
