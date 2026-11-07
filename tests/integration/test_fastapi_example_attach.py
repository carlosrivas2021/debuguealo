"""The FastAPI example can be debugged in a real container through Python attach."""

import asyncio
import json
import os
import shutil
import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from debugpilot.debugger import DebugError, PythonAttachSession
from debugpilot.storage.code_projects import CodeProject, RemoteAttach

pytestmark = pytest.mark.integration

EXAMPLE = (Path(__file__).parents[2] / 'examples' / 'fastapi-debug').resolve()
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        return reservation.getsockname()[1]


def http(method, url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=data, method=method, headers={'Content-Type': 'application/json'})
    try:
        with OPENER.open(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


async def compose(env, *arguments):
    process = await asyncio.create_subprocess_exec(
        'docker', 'compose', '-p', env['PROJECT'], '-f', str(EXAMPLE / 'compose.yaml'),
        *arguments, env={**os.environ, **env},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    output, _ = await process.communicate()
    return process.returncode, output.decode(errors='replace')


async def healthy(base):
    async with asyncio.timeout(60):
        while True:
            try:
                status, _ = await asyncio.to_thread(http, 'GET', f'{base}/health')
                if status == 200:
                    return
            except (OSError, ValueError):
                pass
            await asyncio.sleep(0.2)


async def stopped(session):
    async with asyncio.timeout(30):
        while session.state != 'stopped':
            await session.events.get()


async def test_breakpoint_in_container_pauses_inspects_and_detaches():
    if shutil.which('docker') is None:
        pytest.skip('docker is not available')
    api_port, dap_port = free_port(), free_port()
    env = {'PROJECT': f'dp-demo-fastapi-test-{api_port}',
           'FASTAPI_DEBUG_API_PORT': str(api_port), 'FASTAPI_DEBUG_DAP_PORT': str(dap_port)}
    code, output = await compose(env, 'up', '--build', '-d')
    if code != 0 and 'Cannot connect' in output:
        pytest.skip(output)
    base = f'http://127.0.0.1:{api_port}'
    source = EXAMPLE / 'app' / 'payments.py'
    line = next(number for number, text in enumerate(
        source.read_text(encoding='utf-8').splitlines(), 1) if 'fee_cents =' in text)
    profile = CodeProject('FastAPI example', EXAMPLE, (),
                          python_attach=RemoteAttach('127.0.0.1', dap_port, '/workspace'))
    payment = {'amount_cents': 1000, 'currency': 'EUR', 'card_token': 'tok_ok'}
    try:
        assert code == 0, output
        await healthy(base)
        session = PythonAttachSession(timeout=20)
        try:
            await session.start(profile, {source: [line]})
        except DebugError as error:
            pytest.fail(f'attach failed: {error}')
        assert session.verified_breakpoints[str(source)][0]['verified'] is True
        request = asyncio.create_task(asyncio.to_thread(http, 'POST', f'{base}/payments', payment))
        await stopped(session)

        frames = await session.stack()
        assert frames[0]['source']['path'] == str(source)
        assert frames[0]['name'] == 'process_payment'
        assert frames[0]['line'] == line
        scopes = await session.scopes(frames[0]['id'])
        variables = await session.variables(scopes[0]['variablesReference'])
        assert next(v for v in variables if v['name'] == 'amount')['value'] == '1000'

        # Disconnecting while paused releases the waiting request and keeps the API alive.
        await session.close()
        assert session.disconnect_warning is None
        status, body = await asyncio.wait_for(request, 30)
        assert (status, body['net_cents']) == (200, 970)
        status, _ = await asyncio.to_thread(http, 'GET', f'{base}/health')
        assert status == 200
        declined = {**payment, 'card_token': 'tok_declined'}
        assert (await asyncio.to_thread(http, 'POST', f'{base}/payments', declined))[0] == 402
        assert (await asyncio.to_thread(
            http, 'POST', f'{base}/payments', {'currency': 'EUR'}))[0] == 422
    finally:
        await compose(env, 'down', '--volumes', '--rmi', 'local', '--timeout', '3')
