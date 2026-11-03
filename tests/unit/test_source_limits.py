import os

import pytest
from test_source_browser import BrowserApp
from textual.widgets import TextArea, Tree

from debugpilot.tui.source_browser import SourceBrowser


async def test_preview_rejects_oversized_file_and_escaped_directory(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "large.py"
    source.write_bytes(b"a" * (1024 * 1024 + 1))
    external = tmp_path / "external"
    external.mkdir()
    (external / "secret.py").write_text("not project source", encoding="utf-8")
    folder = root / "folder"
    folder.mkdir()
    app = BrowserApp()
    async with app.run_test() as pilot:
        browser = app.query_one(SourceBrowser)
        browser.set_project(root)
        tree = browser.query_one(Tree)
        file_node = next(n for n in tree.root.children if str(n.label) == "large.py")
        tree.select_node(file_node)
        await pilot.pause()
        assert "1 MiB" in str(browser.query_one("#source-status").render())
        assert browser.query_one(TextArea).text == ""
        assert browser.query_one("#source-breakpoint").disabled
        assert source.stat().st_size == 1024 * 1024 + 1
        # A directory replaced after listing must not disclose the external tree.
        directory = next(n for n in tree.root.children if str(n.label) == "folder")
        folder.rmdir()
        try:
            os.symlink(external, folder, target_is_directory=True)
        except OSError:
            pytest.skip("Creating symlinks requires platform permission")
        directory.expand()
        await pilot.pause()
        assert not directory.children
        assert "outside the selected project" in str(browser.query_one("#source-status").render())
        assert browser.query_one(TextArea).text == ""
