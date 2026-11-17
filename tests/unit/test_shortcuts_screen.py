"""? opens a screen listing the current area's shortcuts, grouped by task."""

import importlib
import inspect
import pkgutil

from test_tui_grouping import until

import debugpilot.tui
from debugpilot.tui.shortcuts import EVERYWHERE, SECTIONS, ShortcutsScreen, shortcut_text


def bound_keys():
    """Every key bound by a debugealo widget, screen or app, base classes included."""
    keys = set()
    for module in pkgutil.iter_modules(debugpilot.tui.__path__):
        loaded = importlib.import_module(f"debugpilot.tui.{module.name}")
        for _, cls in inspect.getmembers(loaded, inspect.isclass):
            for owner in cls.__mro__:
                for binding in owner.__dict__.get("BINDINGS", ()):
                    key = binding.key if hasattr(binding, "key") else binding[0]
                    keys.update(part.strip() for part in key.split(","))
    return keys


def test_every_listed_key_is_bound_somewhere():
    keys = bound_keys()
    listed = [shortcut for _, group in (*SECTIONS["containers"], *SECTIONS["code"], EVERYWHERE)
              for shortcut in group]
    missing = {(shortcut.keys, key) for shortcut in listed for key in shortcut.bindings
               if key not in keys}
    assert not missing, missing


def test_each_area_lists_its_groups_then_the_global_keys():
    containers = shortcut_text("containers").plain
    code = shortcut_text("code").plain
    assert containers.index("Logs") < containers.index("Everywhere")
    assert "Ctrl+L" in containers and "Shift+F5" not in containers
    assert "Shift+F5" in code and "Ctrl+L" not in code
    assert "Breakpoints" in code and "Ctrl+T" in code
    assert "Ctrl+F10" in code and "Ctrl+F10" not in containers  # Run to cursor.


def _title(app):
    return app.screen.query_one("#shortcuts").border_title


async def test_question_mark_opens_the_area_shortcuts_and_tab_switches(monkeypatch, tmp_path):
    from test_code_debug_ui import debug_app

    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        await pilot.press("question_mark")
        await until(pilot, lambda: isinstance(app.screen, ShortcutsScreen))
        assert _title(app) == "Containers · shortcuts"
        text = str(app.screen.query_one("#shortcuts-list").render())
        assert "Ctrl+L" in text and "Everywhere" in text
        await pilot.press("tab")
        assert _title(app) == "Code · shortcuts"
        assert "Shift+F5" in str(app.screen.query_one("#shortcuts-list").render())
        # ? again (or Esc) closes it; a second ? never stacks another screen.
        await pilot.press("question_mark")
        await until(pilot, lambda: not isinstance(app.screen, ShortcutsScreen))

        await pilot.click("#area-code")
        await pilot.press("question_mark")
        await until(pilot, lambda: isinstance(app.screen, ShortcutsScreen))
        assert _title(app) == "Code · shortcuts"
        await pilot.press("escape")
        await until(pilot, lambda: not isinstance(app.screen, ShortcutsScreen))

        # In a text field, ? is typed, never the shortcut.
        await pilot.press("slash")
        field = app.query_one("#code-filter")
        await until(pilot, lambda: field.has_focus)
        await pilot.press("question_mark")
        assert field.value == "?" and not isinstance(app.screen, ShortcutsScreen)


async def test_the_command_palette_keys_opens_the_same_screen(monkeypatch, tmp_path):
    from test_code_debug_ui import debug_app
    from textual.command import CommandPalette

    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        await pilot.click("#area-code")
        await pilot.press("ctrl+p")
        await until(pilot, lambda: isinstance(app.screen, CommandPalette))
        await pilot.press(*"Keys")
        await pilot.pause(0.5)
        await pilot.press("enter")
        # Not Textual's raw HelpPanel: the grouped list of the area on screen.
        await until(pilot, lambda: isinstance(app.screen, ShortcutsScreen))
        assert _title(app) == "Code · shortcuts"
        assert not app.query("HelpPanel")
