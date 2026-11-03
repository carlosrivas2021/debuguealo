import asyncio
import json

import pytest

from debugpilot.debugger.dap import DAPClient, DebugError


async def receive(reader):
    header = await reader.readuntil(b'\r\n\r\n')
    size = int(header.split(b':')[1].strip())
    return json.loads(await reader.readexactly(size))


async def send(writer, message):
    data = json.dumps(message).encode()
    writer.write(f'Content-Length: {len(data)}\r\n\r\n'.encode() + data)
    await writer.drain()


async def test_dap_correlates_response_and_event_and_rejects_reverse_requests():
    finished = asyncio.Event()

    async def adapter(reader, writer):
        try:
            request = await receive(reader)
            await send(writer, {'type': 'event', 'event': 'stopped', 'body': {'threadId': 7}})
            await send(writer, {'seq': 99, 'type': 'request', 'command': 'runInTerminal'})
            rejection = await receive(reader)
            assert rejection['success'] is False
            assert rejection['request_seq'] == 99
            await send(writer, {'type': 'response', 'request_seq': request['seq'],
                                'success': True, 'body': {'answer': 42}})
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            finished.set()

    events = []
    async with await asyncio.start_server(adapter, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        client = DAPClient(reader, writer, events.append, timeout=1)
        try:
            assert await client.request('stackTrace') == {'answer': 42}
            assert events == [{'type': 'event', 'event': 'stopped', 'body': {'threadId': 7}}]
        finally:
            await client.close()
            await client.close()
        await asyncio.wait_for(finished.wait(), 2)


@pytest.mark.parametrize('failure', ['disconnect', 'timeout', 'oversize'])
async def test_dap_pending_request_fails_boundedly(failure):
    finished = asyncio.Event()

    async def adapter(reader, writer):
        try:
            await receive(reader)
            if failure == 'oversize':
                writer.write(b'Content-Length: 999999999\r\n\r\n')
                await writer.drain()
            if failure != 'disconnect':
                await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            finished.set()

    async with await asyncio.start_server(adapter, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        client = DAPClient(reader, writer, lambda event: None, timeout=0.2)
        try:
            with pytest.raises(DebugError):
                await client.request('initialize')
        finally:
            await client.close()
        await asyncio.wait_for(finished.wait(), 2)
