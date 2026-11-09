"""The dashboard follows, filters and visually pauses a real container's logs."""

import asyncio
import json
import uuid

import pytest
from textual.widgets import DataTable, Input

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.docker.diagnostics import DockerDiagnostics
from debugpilot.docker.service import DockerService
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.log_viewer import LogViewer

pytestmark = pytest.mark.integration

LOOP = '''\
import itertools, time
for number in itertools.count():
    print(("ALPHA" if number % 2 else "BETA"), number, flush=True)
    time.sleep(0.05)
'''


async def docker(*arguments):
    process = await asyncio.create_subprocess_exec(
        'docker', *arguments,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    output, _ = await process.communicate()
    return process.returncode, output.decode(errors='replace').strip()


async def wait_until(pilot, condition):
    async with asyncio.timeout(30):
        while not condition():
            await pilot.pause(0.05)


def texts(items):
    return [item.text for item in items]


async def test_live_logs_filter_and_visual_pause_leave_the_container_running(tmp_path):
    settings = Settings()
    if (await DockerDiagnostics(settings).inspect())[0].status != 'ok':
        pytest.skip('docker is not available')
    name = f'debugealo-test-logs-{uuid.uuid4().hex[:12]}'
    code, container_id = await docker(
        'run', '-d', '--rm', '--name', name, 'python:3.12-alpine', 'python', '-c', LOOP)
    assert code == 0, container_id
    app = DebugPilotApp(DebugPilotEngine(settings, docker=DockerService(settings)),
                        refresh_interval=0.2, workspace=tmp_path)
    try:
        async with app.run_test(size=(140, 45)) as pilot:
            table = app.query_one('#launch-profiles', DataTable)
            key = f'container:{container_id}'
            await wait_until(pilot, lambda: key in table.rows)
            table.focus()
            table.move_cursor(row=table.get_row_index(key))
            app._select_focused_row(table)
            # Selecting a container shows its details; logs open on demand with Ctrl+L.
            await pilot.press('ctrl+l')
            viewer = app.query_one(LogViewer)

            # Live: new lines keep arriving without any further action.
            await wait_until(pilot, lambda: len(viewer.visible_entries) >= 3)
            seen = len(viewer.visible_entries)
            await wait_until(pilot, lambda: len(viewer.visible_entries) > seen)

            # Filter: only matching lines stay visible while the stream continues.
            viewer.query_one('#filter-logs', Input).value = 'ALPHA'
            await wait_until(pilot, lambda: bool(viewer.visible_entries) and all(
                'ALPHA' in text for text in texts(viewer.visible_entries)))
            viewer.query_one('#filter-logs', Input).value = ''
            await wait_until(pilot, lambda: any(
                'BETA' in text for text in texts(viewer.visible_entries)))

            # Pause: the view freezes, ingestion continues and the container is untouched.
            viewer.query_one('#pause-logs').press()
            await wait_until(pilot, lambda: viewer.paused)
            await pilot.pause(0.2)
            frozen = texts(viewer.visible_entries)
            buffered = texts(viewer.buffer.entries())[-1]
            await wait_until(pilot, lambda: texts(viewer.buffer.entries())[-1] != buffered)
            await pilot.pause(0.5)
            assert texts(viewer.visible_entries) == frozen
            code, state = await docker('inspect', '--format', '{{json .State}}', name)
            assert code == 0, state
            state = json.loads(state)
            assert (state['Running'], state['Paused']) == (True, False)

            viewer.query_one('#pause-logs').press()
            await wait_until(pilot, lambda: not viewer.paused
                             and texts(viewer.visible_entries) != frozen)
    finally:
        await docker('rm', '-f', name)
