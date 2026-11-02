"""The lower console starts hidden and appears only after an explicit action."""

import pytest
from test_tui_central_terminal import assert_files_unchanged, central_app
from test_tui_grouping import until
from textual.widgets import DataTable

from debugpilot.tui.execution_console import ExecutionConsole
from debugpilot.tui.terminal_view import TerminalPane


@pytest.mark.asyncio
async def test_console_starts_hidden_o_restores_and_host_open_reveals_it(tmp_path, monkeypatch):
    app, docker, made, _workspace, service, launch, compose, original = central_app(
        tmp_path, monkeypatch
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: docker.requested == 2)
        console = app.query_one(ExecutionConsole)
        dashboard = app.query_one("#dashboard")
        assert not console.display and console.region.height == 0
        assert made == [] and not app.query_one("#terminal-pane", TerminalPane).active
        full_height = dashboard.region.height
        app.query_one("#launch-profiles", DataTable).focus()
        await pilot.press("o")
        await pilot.pause()
        assert console.display and console.region.height > 0
        assert dashboard.region.height + console.region.height == full_height
        assert made == []
        await pilot.press("o")
        await pilot.pause()
        assert not console.display and dashboard.region.height == full_height
        assert made == []
        await pilot.press("h")
        await pilot.pause()
        pane = app.query_one("#terminal-pane", TerminalPane)
        assert len(made) == 1 and made[0].host[0] == service.resolve()
        assert console.display and pane.active and app.focused is pane
        await pilot.click("#terminal-close")
        await pilot.pause()
        assert made[0].closed and not pane.active
        assert_files_unchanged(launch, compose, original)
