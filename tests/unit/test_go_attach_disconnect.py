"""Regression coverage for non-owning Go attach disconnect behavior."""

import asyncio
import os
import shutil
import socket
import urllib.request
from pathlib import Path

import pytest

from debugpilot.debugger import GoAttachSession
from debugpilot.storage.code_projects import CodeProject, GoAttach


@pytest.mark.parametrize('disconnect_while_stopped', [True, False], ids=['stopped', 'running'])
async def test_disconnect_resumes_external_http_target_and_reconnects_breakpoint(
        tmp_path, disconnect_while_stopped):
    repository = Path(__file__).parents[2]
    dlv = shutil.which('dlv') or str(repository / '.tools' / 'bin' / 'dlv')
    if not await asyncio.to_thread(Path(dlv).is_file):
        pytest.skip('Delve is not installed in the repository environment.')

    remote = tmp_path / 'remote'
    local = tmp_path / 'workspace'
    remote.mkdir()
    local.mkdir()
    remote_source, local_source = remote / 'main.go', local / 'main.go'
    source = '''package main

import (
    "fmt"
    "net/http"
)

func main() {
    http.HandleFunc("/hello", func(w http.ResponseWriter, r *http.Request) {
        fmt.Fprint(w, "hello from external Go target")
    })
    http.ListenAndServe("127.0.0.1:0", nil)
}
'''
    remote_source.write_text(source, encoding='utf-8')
    local_source.write_text(source, encoding='utf-8')
    # Line 11 is inside the HTTP handler and executes after server initialization.
    breakpoint_line = 11
    (remote / 'go.mod').write_text(
        'module example.invalid/disconnect\n\ngo 1.22\n', encoding='utf-8')
    (local / 'launch.json').write_bytes(b'{"keep":"launch bytes"}\n')
    launch_bytes = (local / 'launch.json').read_bytes()
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        dap_port = reserve.getsockname()[1]
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        http_port = reserve.getsockname()[1]
    # Set the actual HTTP listener port in source before Delve builds the target.
    source = source.replace('127.0.0.1:0', f'127.0.0.1:{http_port}')
    remote_source.write_text(source, encoding='utf-8')
    local_source.write_text(source, encoding='utf-8')
    source_bytes = local_source.read_bytes(), remote_source.read_bytes()

    go_env = {**os.environ, 'GOTOOLCHAIN': 'local', 'GOWORK': 'off',
              'GOPROXY': 'off', 'GOSUMDB': 'off'}
    # Build first, with the same unoptimized flags as `dlv debug`. A cold build cache can
    # take tens of seconds under load and must not eat into Delve's startup deadline.
    binary = tmp_path / 'target'
    build = await asyncio.create_subprocess_exec(
        shutil.which('go') or 'go', 'build', '-gcflags=all=-N -l', '-o', str(binary), '.',
        cwd=remote, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env=go_env,
    )
    try:
        async with asyncio.timeout(300):
            build_output, _ = await build.communicate()
    except TimeoutError:
        build.kill()
        await build.wait()
        pytest.fail('Building the Go fixture took longer than 300 s.')
    assert build.returncode == 0, build_output.decode(errors='replace')

    process = await asyncio.create_subprocess_exec(
        dlv, 'exec', str(binary), '--headless', '--accept-multiclient', '--api-version=2',
        '--listen', f'127.0.0.1:{dap_port}', cwd=remote,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=go_env,
    )
    startup_lines = []
    listening = asyncio.Event()

    async def capture_stdout():
        while line := await process.stdout.readline():
            text = line.decode('utf-8', errors='replace').rstrip()
            startup_lines.append(text)
            if 'API server listening at:' in text:
                listening.set()

    stdout_reader = asyncio.create_task(capture_stdout())
    target = CodeProject('owned disconnect fixture', local, (), None,
                         GoAttach('127.0.0.1', dap_port, remote.as_posix()))
    session = GoAttachSession(timeout=10)

    async def http_get():
        def request():
            url = f'http://127.0.0.1:{http_port}/hello'
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.status, response.read(), response.headers.get('Content-Length')
        return await asyncio.to_thread(request)

    async def wait_stopped():
        async with asyncio.timeout(8):
            while session.state != 'stopped':
                await session.events.get()

    async def wait_http_listener():
        async with asyncio.timeout(8):
            while True:
                try:
                    reader, writer = await asyncio.open_connection('127.0.0.1', http_port)
                    writer.close()
                    await writer.wait_closed()
                    return
                except OSError:
                    await asyncio.sleep(0.05)

    try:
        # Wait for the owned server's startup message; a probe socket is rejected by Delve.
        try:
            async with asyncio.timeout(15):
                await listening.wait()
        except TimeoutError:
            pytest.fail(f'Delve did not listen: exit={process.returncode}; '
                        f'stdout={startup_lines!r}')
        await session.start(target, {local_source: [breakpoint_line]})
        assert session.requested_breakpoints == {str(local_source.resolve()): (breakpoint_line,)}
        await wait_http_listener()
        pending_request = asyncio.create_task(http_get())
        await wait_stopped()
        if not disconnect_while_stopped:
            await session.continue_execution()
            assert session.state == 'running'
            assert (await pending_request)[:2] == (200, b'hello from external Go target')

        await session.close()
        if disconnect_while_stopped:
            assert (await pending_request)[:2] == (200, b'hello from external Go target')
        assert session.requested_breakpoints == {str(local_source.resolve()): (breakpoint_line,)}
        assert (local / 'launch.json').read_bytes() == launch_bytes
        assert (local_source.read_bytes(), remote_source.read_bytes()) == source_bytes
        # This request must complete even when Disconnect was issued at a breakpoint.
        status, body, _ = await http_get()
        assert (status, body) == (200, b'hello from external Go target')
        assert process.returncode is None

        await session.start(target, {local_source: [breakpoint_line]})
        reconnected_request = asyncio.create_task(http_get())
        await wait_stopped()
        assert session.requested_breakpoints == {str(local_source.resolve()): (breakpoint_line,)}
        await session.close()
        assert (await reconnected_request)[:2] == (200, b'hello from external Go target')
        assert process.returncode is None
    finally:
        await session.close()
        if process.returncode is None:
            process.terminate()
        await asyncio.wait_for(process.wait(), 5)
        _, stderr = await process.communicate()
        await asyncio.gather(stdout_reader, return_exceptions=True)
        assert not stderr, f'unexpected Delve stderr: {stderr.decode(errors="replace")}'
        assert process.returncode is not None
