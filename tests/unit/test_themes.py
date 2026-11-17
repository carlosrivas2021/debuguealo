"""The debugealo theme is the default, and the theme picked in the app is remembered."""

import json

import pytest
from test_tui_grouping import Docker, until

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.config import Settings
from debugpilot.storage.ui_theme import ThemeStore
from debugpilot.tui.app import DebugPilotApp


def make_app():
    return DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()))


def test_store_round_trip_and_absence(tmp_path):
    store = ThemeStore(tmp_path / "theme.json")
    assert store.load() is None and not store.path.exists()
    store.save("tokyo-night")
    assert store.load() == "tokyo-night"
    assert json.loads(store.path.read_text()) == {"version": 1, "theme": "tokyo-night"}


@pytest.mark.parametrize("content", [
    "not json", '{"version": 2, "theme": "nord"}', '{"version": 1, "theme": "Bad Name"}',
    '{"version": 1, "theme": "nord", "extra": 1}',
])
def test_invalid_store_is_reported_and_never_replaced(tmp_path, content):
    store = ThemeStore(tmp_path / "theme.json")
    store.path.write_text(content)
    with pytest.raises(ConfigurationError, match="Invalid saved theme"):
        store.load()
    with pytest.raises(ConfigurationError, match="Invalid saved theme"):
        store.save("nord")
    assert store.path.read_text() == content


def test_store_default_location_is_beside_the_settings(tmp_path):
    assert ThemeStore().path == tmp_path / ".debugpilot" / "theme.json"


async def test_debugealo_is_the_default_and_nothing_is_written(tmp_path):
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.theme == "debugealo"
        assert app.screen.styles.background.hex == "#080B0E"
    assert not ThemeStore().path.exists()


async def test_a_picked_theme_is_remembered_for_the_next_session(tmp_path):
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.theme = "nord"
        await until(pilot, lambda: ThemeStore().path.exists())
    assert ThemeStore().load() == "nord"
    restarted = make_app()
    async with restarted.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert restarted.theme == "nord"


@pytest.mark.parametrize("content,message", [
    ('{"version": 1, "theme": "no-such-theme"}', "Unknown saved theme 'no-such-theme'"),
    ("not json", "Invalid saved theme"),
])
async def test_a_bad_saved_theme_falls_back_with_a_warning(monkeypatch, content, message):
    store = ThemeStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(content)
    notes = []
    app = make_app()
    monkeypatch.setattr(app, "notify", lambda text, **_: notes.append(text))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.theme == "debugealo"
        assert any(message in note for note in notes)
    assert store.path.read_text() == content


async def test_every_theme_loads_and_recolors_the_app(monkeypatch, tmp_path):
    from test_code_debug_ui import debug_app

    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.click("#area-code")
        await pilot.pause()
        sidebar = app.query_one("#source-sidebar")
        title = app.query_one("#source-files-title")
        dark = sidebar.styles.background.hex, title.styles.color.hex
        assert dark == ("#101518", "#A9C2CC")  # The debugealo palette, as before.
        for name in sorted(app.available_themes):
            app.theme = name  # A theme without some variable would fail to parse here.
            await pilot.pause()
            variables = app.get_css_variables()
            assert sidebar.styles.background.hex.upper() == variables["surface"].upper(), name
        app.theme = "textual-light"
        await pilot.pause()
        assert (sidebar.styles.background.hex, title.styles.color.hex) != dark
        assert app.screen.styles.background.hex == app.get_css_variables()["background"].upper()


async def test_text_drawn_from_python_follows_the_theme(monkeypatch, tmp_path):
    from test_code_debug_ui import debug_app, mark
    from test_tui_grouping import select_key

    from debugpilot.storage.breakpoints import BreakpointOptions
    from debugpilot.tui.code_debug import CodeDebug
    from debugpilot.tui.container_details import ContainerDetails
    from debugpilot.tui.theme import _rich_color

    def color(name):
        return tuple(_rich_color(app.get_css_variables(), name).get_truecolor())

    def span_colors(text):
        """RGB of each span, whether Rich Text or Textual Content drew it."""
        colors = set()
        for span in text.spans:
            style = span.style
            if getattr(style, "color", None) is not None:
                colors.add(tuple(style.color.get_truecolor()))
            elif getattr(style, "foreground", None) is not None:
                colors.add(style.foreground.rgb)
        return colors

    app, roots, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click("#area-code")
        browser = await mark(pilot, app, 4)
        source = (roots[0] / "main.py").resolve()
        browser._apply_breakpoint((roots[0].resolve(), source), 4, True,
                                  BreakpointOptions(condition="answer > 1"))
        await pilot.press("shift+f5")
        debug = app.query_one(CodeDebug)
        await until(pilot, lambda: debug.selected is not None
                    and debug.selected.execution is not None)
        await until(pilot, lambda: app.query_one("#code-variables").row_count > 0)

        app.theme = "textual-light"
        await pilot.pause(0.3)
        variables = app.query_one("#code-variables")
        heading = variables.get_row_at(0)[0]
        assert tuple(heading.style.color.get_truecolor()) == color("text-secondary")
        profiles = app.query_one("#code-projects")
        label = profiles.get_row_at(0)[0]
        assert color("text-warning") in span_colors(label)  # The ◉ of a debugging profile.
        listed = app.query_one("#source-breakpoints").get_row_at(0)[0]
        assert color("text-muted") in span_colors(listed)  # "if answer > 1".
        await pilot.press("f5")

        await pilot.click("#area-containers")
        select_key(app, next(key for key in app._rows if key.startswith("container:")))
        await pilot.pause(0.3)
        app.theme = "nord"
        await pilot.pause(0.3)
        card = app.query_one(ContainerDetails).cards()[0].render()
        assert color("text-muted") in span_colors(card)  # The "State:" labels.
