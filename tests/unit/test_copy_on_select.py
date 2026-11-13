"""Selecting text with the mouse copies it right away and says so."""

from test_code_run_ui import setup_app


def _messages(app):
    return [item.message for item in app._notifications]


async def _drag(pilot, app, selector, start, end):
    widget = app.query_one(selector)
    content, region = widget.content_region, widget.region
    x, y = content.x - region.x, content.y - region.y
    await pilot.mouse_down(selector, offset=(x + start, y))
    await pilot.hover(selector, offset=(x + end, y))
    await pilot.mouse_up(selector, offset=(x + end, y))
    await pilot.pause()


async def test_selecting_text_copies_it_and_notifies(monkeypatch, tmp_path):
    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    copied = []
    app.copy_to_clipboard = copied.append
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        await pilot.pause()
        state = str(app.query_one("#code-run-state").render())
        assert state.startswith("Ready")

        await _drag(pilot, app, "#code-run-state", 0, 5)

        assert copied == ["Ready"]
        assert "Copied 5 characters" in _messages(app)


async def test_a_plain_click_copies_nothing(monkeypatch, tmp_path):
    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    copied = []
    app.copy_to_clipboard = copied.append
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        await pilot.pause()

        await _drag(pilot, app, "#code-run-state", 2, 2)

        assert copied == []
        assert not any(message.startswith("Copied") for message in _messages(app))


async def test_selecting_in_the_source_viewer_copies_it_and_notifies(monkeypatch, tmp_path):
    """The read-only source keeps its own selection, so it copies on release itself."""
    from textual.widgets import Tree

    (tmp_path / "main.py").write_text("answer = 41\nprint(answer)\n", encoding="utf-8")
    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    copied = []
    app.copy_to_clipboard = copied.append
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        tree = app.query_one("#source-tree", Tree)
        tree.select_node(next(n for n in tree.root.children if str(n.label) == "main.py"))
        await pilot.pause()
        editor = app.query_one("#source-text")
        start = editor.gutter_width

        await _drag(pilot, app, "#source-text", start, start + 6)

        assert copied == ["answer"]
        assert "Copied 6 characters" in _messages(app)

        copied.clear()
        await _drag(pilot, app, "#source-text", start + 2, start + 2)
        assert copied == []


async def test_dragging_a_selection_repaints_only_what_changed(monkeypatch, tmp_path):
    """Textual would repaint the whole screen on every move; the terminal then lags."""
    from textual._compositor import Compositor

    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    full = []
    original = Compositor.render_full_update

    def counted(self, *args, **kwargs):
        full.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Compositor, "render_full_update", counted)
    copied = []
    app.copy_to_clipboard = copied.append
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.click("#area-code")
        await pilot.pause()
        widget = app.query_one("#code-run-state")
        x = widget.content_region.x - widget.region.x
        await pilot.mouse_down("#code-run-state", offset=(x, 0))
        await pilot.pause()
        full.clear()
        for end in range(1, 21):
            await pilot.hover("#code-run-state", offset=(x + end, 0))
        await pilot.mouse_up("#code-run-state", offset=(x + 20, 0))
        await pilot.pause()

        assert len(full) <= 2
        assert copied == [str(widget.render())[:20]]
