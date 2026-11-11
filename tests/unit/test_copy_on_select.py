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
