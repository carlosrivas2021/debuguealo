from textual.app import App
from textual.widgets import TextArea, Tree

from debugpilot.tui.source_browser import SourceBrowser


class BrowserApp(App):
    def compose(self):
        yield SourceBrowser()


async def test_browse_source_and_toggle_pending_breakpoint_without_writes(tmp_path):
    source = tmp_path / "main.py"
    original = b"print('one')\nprint('two')\n"
    source.write_bytes(original)
    app = BrowserApp()
    async with app.run_test(size=(120, 40)) as pilot:
        browser = app.query_one(SourceBrowser)
        browser.set_project(tmp_path)
        tree = browser.query_one(Tree)
        node = next(child for child in tree.root.children if str(child.label) == "main.py")
        tree.select_node(node)
        await pilot.pause()
        editor = browser.query_one(TextArea)
        assert editor.text == original.decode()
        assert editor.read_only
        editor.move_cursor((1, 0))
        await pilot.click("#source-breakpoint")
        assert browser.breakpoints(tmp_path, source) == (2,)
        assert "pending" in str(node.children[0].label)
        assert "2" in str(node.children[0].label)
        assert "verified" not in str(node.children[0].label)
        tree.select_node(node.children[0])
        await pilot.pause()
        assert editor.cursor_location[0] == 1
        await pilot.pause(0.3)
        await pilot.click("#source-breakpoint")
        assert browser.breakpoints(tmp_path, source) == ()
        assert not node.children
        editor.focus()
        await pilot.press("x", "backspace")
        assert editor.text == original.decode()
        assert source.read_bytes() == original


async def test_project_context_and_safe_unreadable_sources(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "main.py").write_text("first\n", encoding="utf-8")
    (second / "main.py").write_text("second\n", encoding="utf-8")
    (first / "binary.bin").write_bytes(b"\x00\xff")
    app = BrowserApp()
    async with app.run_test() as pilot:
        browser = app.query_one(SourceBrowser)
        browser.set_project(first)
        tree = browser.query_one(Tree)
        node = next(child for child in tree.root.children if str(child.label) == "main.py")
        tree.select_node(node)
        await pilot.pause()
        await pilot.click("#source-breakpoint")
        browser.set_project(second)
        assert browser.query_one(TextArea).text == ""
        assert browser.breakpoints(second, second / "main.py") == ()
        browser.set_project(first)
        assert browser.breakpoints(first, first / "main.py") == (1,)
        binary = next(child for child in tree.root.children if str(child.label) == "binary.bin")
        tree.select_node(binary)
        await pilot.pause()
        assert browser.query_one(TextArea).text == ""
        assert "Unable to open" in str(browser.query_one("#source-status").render())
        assert browser.query_one("#source-breakpoint").disabled
        browser.set_project(None)
        assert not tree.root.children
        assert browser.query_one(TextArea).text == ""
    assert (first / "binary.bin").read_bytes() == b"\x00\xff"


async def test_lazy_directory_expansion_and_missing_file(tmp_path):
    folder = tmp_path / "src"
    folder.mkdir()
    source = folder / "app.py"
    source.write_text("pass\n", encoding="utf-8")
    app = BrowserApp()
    async with app.run_test() as pilot:
        browser = app.query_one(SourceBrowser)
        browser.set_project(tmp_path)
        tree = browser.query_one(Tree)
        directory = tree.root.children[0]
        assert not directory.children
        directory.expand()
        await pilot.pause()
        node = directory.children[0]
        assert str(node.label) == "app.py"
        source.unlink()
        tree.select_node(node)
        await pilot.pause()
        assert "Unable to open" in str(browser.query_one("#source-status").render())
        assert browser.query_one(TextArea).text == ""
    assert not source.exists()
