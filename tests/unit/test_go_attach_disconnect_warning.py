"""A dropped Delve transport must leave a visible, truthful disconnect warning."""

import asyncio
import json

from test_code_debug_ui import debug_app, rendered
from test_go_attach import DAPPeer


class DroppedPeer(DAPPeer):
    async def _send(self, writer, message):
        if (message.get('command') == 'setBreakpoints'
                and not self.requests[-1]['arguments']['breakpoints']):
            writer.close()
            return
        await super()._send(writer, message)


async def test_stop_surfaces_breakpoint_clear_transport_warning(monkeypatch, tmp_path):
    peer = DroppedPeer()
    await peer.start()
    try:
        app, roots, launch_store = debug_app(monkeypatch, tmp_path / 'ui')
        source = roots[0] / 'main.go'
        source.write_text('package main\n')
        config = json.loads(launch_store.path.read_text(encoding='utf-8'))
        config['configurations'][0].pop('command')
        config['configurations'][0]['goAttach'] = {
            'host': '127.0.0.1', 'port': peer.port, 'remoteRoot': '/owned',
        }
        launch_store.path.write_text(json.dumps(config), encoding='utf-8')

        async with app.run_test(size=(140, 52)) as pilot:
            await pilot.click('#area-code')
            browser = app.query_one('#source-browser')
            assert browser.open_source(roots[0], source, 1)
            await pilot.click('#source-breakpoint')
            requested_marks = browser.breakpoints(roots[0], source)
            launch_bytes = launch_store.path.read_bytes()
            breakpoint_store = browser.breakpoint_store
            breakpoint_bytes = breakpoint_store.path.read_bytes()
            source_bytes = source.read_bytes()

            await pilot.press('shift+f5')
            debug = app.query_one('#code-debug')
            async with asyncio.timeout(3):
                while not debug.session or debug.session.state != 'stopped':
                    await pilot.pause(0.01)
            intent = dict(debug.session.requested_breakpoints)
            await pilot.click('#code-stop')

            assert debug.session.state == 'closed'
            output = '\n'.join(line.text for line in
                               app.query_one('#code-debug-output').lines)
            status = rendered(app, '#code-run-state')
            assert 'Unable to clear Go session breakpoints' in output
            assert 'unknown' in status.lower()
            assert browser.breakpoints(roots[0], source) == requested_marks == (1,)
            assert debug.session.requested_breakpoints == intent
            assert launch_store.path.read_bytes() == launch_bytes
            assert breakpoint_store.path.read_bytes() == breakpoint_bytes
            assert source.read_bytes() == source_bytes
            commands = [request['command'] for request in peer.requests]
            assert not any(command in {'launch', 'terminate'} for command in commands)
            assert status != 'Disconnected; target remains managed by Containers'
            assert not app.query_one('#code-reconnect').display
    finally:
        await peer.close()
