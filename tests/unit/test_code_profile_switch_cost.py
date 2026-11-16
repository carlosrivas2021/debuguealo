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


async def test_moving_between_profiles_rebuilds_the_footer_only_when_its_keys_change(
        monkeypatch, tmp_path):
    from test_code_debug_ui import debug_app
    from textual.widgets import Footer
    from textual.widgets._footer import FooterKey

    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click("#area-code")
        table = app.query_one("#code-projects", DataTable)
        await until(pilot, lambda: table.row_count == 2)
        table.focus()
        await pilot.pause(0.3)
        footer = app.query_one(Footer)

        def shown():
            return {key.description for key in footer.query(FooterKey)}

        assert "Reload" in shown() and "Restart" not in shown()
        rebuilt = []
        recompose = Footer.recompose

        async def counted(self):
            rebuilt.append(self)
            return await recompose(self)

        monkeypatch.setattr(Footer, "recompose", counted)
        for key in ("down", "up", "down", "up"):
            await pilot.press(key)
            await pilot.pause()
        # Two stopped profiles offer the same keys: the footer is left as it is.
        assert rebuilt == []
        # Starting a debug session changes the keys (R restarts): the footer follows.
        await pilot.press("shift+f5")
        await until(pilot, lambda: "Restart" in shown())
        assert rebuilt and "Reload" not in shown()
