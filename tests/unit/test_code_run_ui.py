import asyncio
import json
import sys

from test_code_project_store import configure
from test_tui_grouping import Docker, until
from textual.widgets import DataTable, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


def setup_app(monkeypatch, tmp_path, script):
    store = configure(monkeypatch, tmp_path)
    store.path.write_text(json.dumps({'version': 1, 'configurations': [{
        'name': 'Sample', 'workspaceFolder': str(tmp_path),
        'command': [sys.executable, '-u', '-c', script],
    }]}), encoding='utf-8')
    return DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)


async def test_f5_runs_only_code_and_preserves_session_across_areas(monkeypatch, tmp_path):
    marker = tmp_path / 'runs'
    script = (
        f"from pathlib import Path; p=Path({str(marker)!r}); "
        "p.write_text(p.read_text()+'x' if p.exists() else 'x'); "
        "print('READY',flush=True); print('GOT:'+input(),flush=True)"
    )
    app = setup_app(monkeypatch, tmp_path, script)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press('f5')
        assert not marker.exists()
        await pilot.click('#area-code')
        await pilot.press('f5')
        pane = app.query_one('#code-terminal')
        await until(pilot, lambda: 'READY' in pane.render().plain)
        assert marker.read_text() == 'x'
        app.query_one('#code-projects', DataTable).focus()
        await pilot.press('f5')
        assert marker.read_text() == 'x'
        await pilot.click('#area-containers')
        assert pane.active
        await pilot.click('#area-code')
        pane.focus()
        await pilot.press('h', 'i', 'enter')
        await until(pilot, lambda: 'Exited: 0' in str(app.query_one('#code-run-state').render()))
        assert 'GOT:hi' in pane.render().plain
        app.query_one('#code-projects', DataTable).focus()
        await pilot.press('f5')
        await until(pilot, lambda: marker.read_text() == 'xx')
        await pilot.click('#code-stop')
        assert not pane.active
        assert 'Stopped' in str(app.query_one('#code-run-state').render())


async def test_stop_during_startup_and_shutdown(monkeypatch, tmp_path):
    from debugpilot.terminal.code_session import CodeSession

    entered = asyncio.Event()
    gate = asyncio.Event()
    original = CodeSession.open_command

    async def delayed(self, *args):
        entered.set()
        await gate.wait()
        await original(self, *args)

    monkeypatch.setattr(CodeSession, 'open_command', delayed)
    app = setup_app(monkeypatch, tmp_path, "import time; time.sleep(30)")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('f5')
        await asyncio.wait_for(entered.wait(), 3)
        await pilot.click('#code-stop')
        assert not app.query_one('#code-terminal').active
        assert 'Stopped' in str(app.query_one('#code-run-state', Static).render())
        pane = app.query_one('#code-terminal')
        entered.clear()
        await pilot.press('f5')
        await asyncio.wait_for(entered.wait(), 3)
    gate.set()
    assert not pane.active


async def test_shutdown_removes_running_descendants(monkeypatch, tmp_path):
    ready = tmp_path / 'ready'
    survived = tmp_path / 'survived'
    child = (
        f"import time; from pathlib import Path; Path({str(ready)!r}).touch(); "
        f"time.sleep(2); Path({str(survived)!r}).touch(); time.sleep(20)"
    )
    script = (
        f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "time.sleep(30)"
    )
    app = setup_app(monkeypatch, tmp_path, script)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('f5')
        await until(pilot, ready.exists)
        pane = app.query_one('#code-terminal')
        assert pane.active
    assert not pane.active
    await asyncio.sleep(2.2)
    assert not survived.exists()


async def test_no_profile_and_missing_executable_report_errors(monkeypatch, tmp_path):
    store = configure(monkeypatch, tmp_path)
    store.path.unlink()  # Exercise a genuinely absent config, not configure's empty file.
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('f5')
        state = app.query_one('#code-run-state', Static)
        assert 'No Code profile selected' in str(state.render())
        assert not store.path.exists()
        store.path.write_text(json.dumps({'version': 1, 'configurations': [{
            'name': 'Missing', 'workspaceFolder': str(tmp_path),
            'command': ['debugpilot-missing-program-12345'],
        }]}), encoding='utf-8')
        await pilot.click('#code-reload')
        await pilot.press('f5')
        await until(pilot, lambda: 'Executable not found' in str(state.render()))
        assert not app.query_one('#code-terminal').active
