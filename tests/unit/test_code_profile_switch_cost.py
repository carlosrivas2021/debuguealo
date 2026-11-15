"""Moving between Code profiles costs the same however many files a profile has."""

import json
import sys
from pathlib import Path

from test_code_debug_ui import configure
from test_tui_grouping import Docker, until
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


async def test_switching_profiles_does_not_resolve_every_file(monkeypatch, tmp_path):
    store = configure(monkeypatch, tmp_path)
    roots = []
    for name in ("one", "two"):
        root = tmp_path / name
        root.mkdir()
        for index in range(80):
            (root / f"file{index}.py").write_text("x = 1\n")
        (root / "sub").mkdir()
        roots.append(root)
    store.path.write_text(json.dumps({"version": 1, "configurations": [
        {"name": root.name, "workspaceFolder": str(root),
         "command": [sys.executable, "main.py"]} for root in roots]}))
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click("#area-code")
        table = app.query_one("#code-projects", DataTable)
        await until(pilot, lambda: table.row_count == 2)
        table.focus()
        await pilot.pause()
        calls = []
        resolve = Path.resolve

        def counted(self, *args, **kwargs):
            calls.append(self)
            return resolve(self, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", counted)
        await pilot.press("down")
        await until(pilot, lambda: str(app.query_one("#source-tree").root.label) == "two")
        await pilot.pause()
        # A handful for the root and the branch, never one or more per file.
        assert len(calls) < 30, len(calls)
