"""The Code area is laid out like an IDE with context-aware footer shortcuts."""

from test_code_run_ui import setup_app
from test_tui_grouping import until


def _shown_keys(app):
    return {
        key
        for key, active in app.screen.active_bindings.items()
        if active.binding.show and active.enabled
        and app.check_action(active.binding.action.removeprefix("app."), ()) is not False
    }


async def test_code_area_places_profiles_left_editor_center_terminal_below_debug_right(
    monkeypatch, tmp_path
):
    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("f5")
        state = app.query_one("#code-run-state")
        await until(pilot, lambda: "Exited: 0" in str(state.render()))
        debug = app.query_one("#code-debug")
        debug.display = True  # Normally shown only while a debug session is selected.
        await pilot.pause()
        profiles = app.query_one("#code-projects").region
        tree = app.query_one("#source-tree").region
        editor = app.query_one("#source-text").region
        terminal = app.query_one("#code-terminal").region
        side = debug.region
        assert profiles.right <= editor.x and tree.right <= editor.x
        assert profiles.y < tree.y
        assert side.x >= editor.right and side.y == app.query_one("#source-pane").region.y
        assert terminal.y >= editor.bottom and terminal.x == app.query_one("#source-pane").region.x
        assert terminal.right >= side.right
        assert not app.query("#code-capabilities")


async def test_ctrl_j_hides_and_shows_the_code_terminal(monkeypatch, tmp_path):
    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("f5")
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: "Exited: 0" in str(app.query_one("#code-run-state").render()))
        editor_height = app.query_one("#source-text").region.height
        app.query_one("#code-projects").focus()
        bottom = app.query_one("#code-bottom")
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert not bottom.display and pane.region.height == 0
        assert app.query_one("#source-text").region.height > editor_height
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert bottom.display and pane.display and pane.region.height > 0


async def test_footer_shows_debug_shortcuts_only_in_the_code_area(monkeypatch, tmp_path):
    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        containers = _shown_keys(app)
        assert not {"f9", "f10", "f11", "shift+f11", "ctrl+j"} & containers
        await pilot.click("#area-code")
        await pilot.pause()
        code = _shown_keys(app)
        assert {"f5", "shift+f5", "f9", "f10", "f11", "shift+f11", "ctrl+j"} <= code


async def test_f5_keeps_focus_on_profiles_and_terminal_shows_when_it_takes_keys(
    monkeypatch, tmp_path
):
    import json
    import sys

    from test_code_project_store import configure
    from test_tui_grouping import Docker
    from textual.widgets import DataTable

    from debugpilot.core.engine import DebugPilotEngine
    from debugpilot.storage.config import Settings
    from debugpilot.tui.app import DebugPilotApp

    store = configure(monkeypatch, tmp_path)
    script = "print('READY', flush=True); print('GOT:' + input(), flush=True)"
    store.path.write_text(json.dumps({"version": 1, "configurations": [
        {"name": name, "workspaceFolder": str(tmp_path),
         "command": [sys.executable, "-u", "-c", script]}
        for name in ("First", "Second")
    ]}), encoding="utf-8")
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click("#area-code")
        table = app.query_one("#code-projects", DataTable)
        pane = app.query_one("#code-terminal")
        await pilot.press("f5")
        await until(pilot, lambda: pane.active and "READY" in pane.render().plain)
        await pilot.pause()
        assert app.focused is table
        await pilot.press("down")
        assert table.cursor_row == 1
        await pilot.press("up")
        await pilot.press("f5")  # Selecting the live run must not steal focus either.
        await pilot.pause()
        assert app.focused is table and table.cursor_row == 0
        assert "typing" not in str(pane.border_title)
        await pilot.click("#code-terminal")
        assert app.focused is pane
        assert "Esc to leave" in str(pane.border_title)
        await pilot.press("h", "i", "enter")
        await until(pilot, lambda: "GOT:hi" in pane.render().plain)
        await pilot.press("escape")
        assert app.focused is table
        assert "typing" not in str(pane.border_title)


async def test_debug_output_sits_at_the_bottom_like_the_run_terminal(monkeypatch, tmp_path):
    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click("#area-code")
        await pilot.pause()
        debug = app.query_one("#code-debug")
        output = app.query_one("#code-debug-output")
        assert not output.display
        debug.display = True  # What a selected debug session does.
        await pilot.pause()
        assert output.display
        assert output not in debug.query("*")
        editor = app.query_one("#source-text").region
        assert output.region.y >= editor.bottom
        assert output.region.x == app.query_one("#source-pane").region.x
        assert output.region.right >= debug.region.right
        app.query_one("#code-projects").focus()
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert output.region.height == 0
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert output.region.height > 0
        debug.display = False
        await pilot.pause()
        assert not output.display


async def test_a_profile_shows_one_bottom_view_when_it_has_a_finished_run_and_debug(
    monkeypatch, tmp_path
):
    from debugpilot.tui.code_debug import DebugContext
    from debugpilot.tui.code_workspace import CodeWorkspace

    app = setup_app(monkeypatch, tmp_path, "print('RUN_DONE')")
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("f5")
        await until(pilot, lambda: "Exited: 0" in str(app.query_one("#code-run-state").render()))
        workspace = app.query_one(CodeWorkspace)
        debug = app.query_one("#code-debug")
        profile = next(iter(workspace._profiles.values()))
        # A debug session of the same profile that already ended keeps its context.
        debug.contexts[profile.name] = DebugContext(profile=profile, key=profile.name)
        workspace.select_source_project()
        await pilot.pause()
        pane = app.query_one("#code-terminal")
        output = app.query_one("#code-debug-output")
        assert pane.display != output.display
        assert pane.display and "RUN_DONE" in pane.render().plain
        assert not debug.display


async def test_finished_debug_view_keeps_output_hides_panel_and_reports_debug_state(
    monkeypatch, tmp_path
):
    from debugpilot.tui.code_debug import DebugContext
    from debugpilot.tui.code_workspace import CodeWorkspace

    app = setup_app(monkeypatch, tmp_path, "print('RUN_DONE')")
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("f5")
        await until(pilot, lambda: "Exited: 0" in str(app.query_one("#code-run-state").render()))
        workspace = app.query_one(CodeWorkspace)
        profile = next(iter(workspace._profiles.values()))
        debug = app.query_one("#code-debug")
        debug.contexts[profile.name] = DebugContext(
            profile=profile, key=profile.name, state="Debug ended: Sample"
        )
        workspace._last_view[profile.name] = "debug"  # The user's last action was Shift+F5.
        workspace.select_source_project()
        await pilot.pause()
        assert app.query_one("#code-debug-output").display
        assert not debug.display, "an ended session must not keep the empty debug panel"
        assert not app.query_one("#code-terminal").display
        state = str(app.query_one("#code-run-state").render())
        assert "Debug ended" in state and "Exited" not in state
        table = app.query_one("#code-projects")
        assert table.columns[next(iter(table.columns))].get_render_width(table) >= 20


async def test_debug_panel_closes_when_the_selected_session_ends_on_its_own(
    monkeypatch, tmp_path
):
    from debugpilot.tui.code_debug import DebugContext
    from debugpilot.tui.code_workspace import CodeWorkspace

    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click("#area-code")
        await pilot.pause()
        workspace = app.query_one(CodeWorkspace)
        profile = next(iter(workspace._profiles.values()))
        debug = app.query_one("#code-debug")
        context = DebugContext(profile=profile, key=profile.name, active=True,
                               state="Debug stopped: Sample")
        debug.contexts[profile.name] = context
        workspace._last_view[profile.name] = "debug"
        workspace.select_source_project()
        await pilot.pause()
        assert debug.display  # Live session: the side panel is shown.
        # The program finished after Continue; the debugger reports completion.
        context.active = False
        context.state = "Debug ended: Sample"
        debug.finished(False)
        await pilot.pause()
        assert not debug.display
        assert app.query_one("#code-debug-output").display
        assert "Debug ended" in str(app.query_one("#code-run-state").render())
