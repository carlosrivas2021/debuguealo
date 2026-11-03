import json

from test_code_project_store import configure
from test_tui_grouping import Docker, until
from textual.widgets import DataTable, TextArea, Tree

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.source_browser import SourceBrowser


async def test_profile_navigation_preserves_source_breakpoints_and_container_context(
    tmp_path, monkeypatch
):
    store = configure(monkeypatch, tmp_path)
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        root.mkdir()
        (root / "main.py").write_text(f"print('{root.name}')\n", encoding="utf-8")
    store.path.write_text(json.dumps({"version": 1, "configurations": [
        {"name": root.name, "workspaceFolder": str(root), "command": ["python", "main.py"]}
        for root in roots
    ]}), encoding="utf-8")
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        selected = app.selected_container
        await pilot.click("#area-code")
        browser = app.query_one(SourceBrowser)
        assert browser.root_path == roots[0].resolve()
        tree = browser.query_one(Tree)
        tree.select_node(tree.root.children[0])
        await pilot.pause()
        assert "one" in browser.query_one(TextArea).text
        await pilot.click("#source-breakpoint")
        profiles = app.query_one("#code-projects", DataTable)
        profiles.focus()
        await pilot.press("down")
        await pilot.pause()
        assert browser.root_path == roots[1].resolve()
        assert browser.query_one(TextArea).text == ""
        assert browser.breakpoints(roots[1], roots[1] / "main.py") == ()
        await pilot.press("up")
        await pilot.pause()
        assert browser.breakpoints(roots[0], roots[0] / "main.py") == (1,)
        await pilot.click("#area-containers")
        assert app.selected_container == selected
        await pilot.click("#area-code")
        assert browser.breakpoints(roots[0], roots[0] / "main.py") == (1,)
        assert "pending" in str(tree.root.children[0].children[0].label)
        store.path.write_text('{"version":1,"configurations":[]}', encoding="utf-8")
        await pilot.click("#code-reload")
        assert browser.root_path is None
        assert not tree.root.children
        assert browser.query_one(TextArea).text == ""
