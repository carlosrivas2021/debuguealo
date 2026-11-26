"""The lower console starts hidden and appears only after an explicit action."""

import pytest
from test_tui_central_terminal import assert_files_unchanged, central_app, click_output_toggle
from test_tui_grouping import until
from textual.widgets import DataTable

from debugpilot.tui.execution_console import ExecutionConsole
from debugpilot.tui.terminal_view import TerminalPane


@pytest.mark.asyncio
async def test_console_starts_collapsed_button_expands_and_host_opens_below(tmp_path, monkeypatch):
    app, docker, made, _workspace, service, launch, compose, original = central_app(
        tmp_path, monkeypatch
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: docker.requested == 2)
        console = app.query_one(ExecutionConsole)
        dashboard = app.query_one("#dashboard")
        sidebar = app.query_one("#sidebar")
        assert console.display and not console.expanded and console.region.height <= 3
        assert made == [] and not app.query_one("#terminal-pane", TerminalPane).active
        full_height = dashboard.region.height
        app.query_one("#launch-profiles", DataTable).focus()
        await click_output_toggle(pilot)
        await pilot.pause()
        assert console.expanded and console.region.height > 3
        # The console docks under the right panel; the project list keeps its full height.
        assert dashboard.region.height == sidebar.region.height == full_height
        assert console.region.x >= app.query_one("#right-panel").region.x
        assert console.region.bottom <= dashboard.region.bottom
        assert made == []
        await click_output_toggle(pilot)
        await pilot.pause()
        assert not console.expanded and dashboard.region.height == full_height
        assert made == []
        await pilot.press("t")
        await pilot.pause()
        pane = app.query_one("#terminal-pane", TerminalPane)
        assert len(made) == 1 and made[0].host[0] == service.resolve()
        # The host shell docks at the bottom of the right panel, apart from the output card.
        host = app.query_one("#host-terminal")
        right = app.query_one("#right-panel")
        assert host.display and pane.active and app.focused is pane
        assert pane.parent is host and host.parent is right
        assert host.region.x >= right.region.x and host.region.bottom == right.region.bottom
        assert app.query_one("#sidebar").region.height == full_height
        made[0].on_exit()  # The user types `exit`.
        await until(pilot, lambda: not pane.active and not host.display)
        assert_files_unchanged(launch, compose, original)


async def test_host_terminal_stays_at_the_bottom_when_the_output_card_is_hidden(
    tmp_path, monkeypatch
):
    app, docker, made, _workspace, _service, _launch, _compose, _original = central_app(
        tmp_path, monkeypatch
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: docker.requested == 2)
        table = app.query_one("#launch-profiles", DataTable)
        child = next(
            row.key.value for row in table.ordered_rows
            if row.key.value.startswith("profile-child:")
        )
        table.focus()
        table.move_cursor(row=table.get_row_index(child))
        await until(pilot, lambda: app.selected_container is not None)
        # Container details have auto height, so nothing else fills the panel.
        await pilot.press("t")
        await pilot.pause()
        host, right = app.query_one("#host-terminal"), app.query_one("#right-panel")
        assert host.display and not app.query_one(ExecutionConsole).expanded
        assert host.region.bottom == right.region.bottom

