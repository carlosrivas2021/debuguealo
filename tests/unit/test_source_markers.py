from test_source_browser import BrowserApp
from textual.widgets import TextArea, Tree

from debugpilot.tui.source_browser import SourceBrowser


async def test_red_breakpoint_button_tracks_line_scroll_and_file_context(tmp_path):
    source = tmp_path / "main.py"
    original = "\n".join(f"print({line})" for line in range(80))
    source.write_bytes(original.encode("utf-8"))
    other = tmp_path / "other.py"
    other.write_text("pass\n", encoding="utf-8")
    app = BrowserApp()
    async with app.run_test(size=(100, 30)) as pilot:
        browser = app.query_one(SourceBrowser)
        browser.set_project(tmp_path)
        tree = browser.query_one(Tree)
        node = next(n for n in tree.root.children if str(n.label) == "main.py")
        tree.select_node(node)
        await pilot.pause()
        editor = browser.query_one(TextArea)
        editor.move_cursor((2, 0))
        await pilot.click("#source-breakpoint")
        strip = editor.render_line(2)
        assert "●" in strip.text
        marker = next(segment for segment in strip if "●" in segment.text)
        assert marker.style.color.triplet == (239, 68, 68)
        assert "3" in strip.text[:editor.gutter_width]
        assert "print(2)" in strip.text
        # Pilot offsets include borders; gutter coordinates are relative to content.
        gutter_x = editor.content_region.x - editor.region.x + editor.gutter_width - 2
        line_y = editor.content_region.y - editor.region.y + 2
        await pilot.click("#source-text", offset=(gutter_x, line_y))
        await pilot.pause()
        assert browser.breakpoints(tmp_path, source) == ()
        assert "●" not in editor.render_line(2).text
        await pilot.click("#source-text", offset=(gutter_x, line_y))
        await pilot.pause()
        assert browser.breakpoints(tmp_path, source) == (3,)
        editor.scroll_to(y=2, animate=False, force=True)
        await pilot.pause()
        assert "●" in editor.render_line(0).text
        tree.select_node(next(n for n in tree.root.children if str(n.label) == "other.py"))
        await pilot.pause()
        assert "●" not in editor.render_line(0).text
        tree.select_node(node)
        await pilot.pause()
        assert "●" in editor.render_line(2).text
        assert not node.children  # Listed under BREAKPOINTS, not in the file tree.
        assert editor.text == original
    assert source.read_text(encoding="utf-8") == original
    assert other.read_text(encoding="utf-8") == "pass\n"


async def test_paused_execution_line_is_shaded_yellow_until_cleared(tmp_path):
    source = tmp_path / "main.py"
    source.write_text("\n".join(f"print({line})" for line in range(10)), encoding="utf-8")
    app = BrowserApp()
    async with app.run_test(size=(100, 30)) as pilot:
        browser = app.query_one(SourceBrowser)
        browser.set_project(tmp_path)
        await pilot.pause()
        browser.show_execution(tmp_path, source, 4)
        await pilot.pause()
        editor = browser.query_one(TextArea)
        shaded = editor.render_line(3)
        assert "▶" in shaded.text
        code = shaded.crop(editor.gutter_width)
        assert code.cell_length > len("print(3)")
        assert all(
            segment.style.bgcolor is not None
            and segment.style.bgcolor.triplet == (107, 93, 0)
            for segment in code if segment.text
        )
        other = editor.render_line(5).crop(editor.gutter_width)
        assert all(
            segment.style is None or segment.style.bgcolor is None
            or segment.style.bgcolor.triplet != (107, 93, 0)
            for segment in other
        )
        browser.clear_execution()
        await pilot.pause()
        cleared = editor.render_line(3)
        assert "▶" not in cleared.text
        assert all(
            segment.style is None or segment.style.bgcolor is None
            or segment.style.bgcolor.triplet != (107, 93, 0)
            for segment in cleared
        )
