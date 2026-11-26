"""Separate terminal views with one owned fake session and explicit navigation."""

import asyncio

import pytest
from test_tui_central_terminal import assert_files_unchanged, central_app
from test_tui_grouping import item, until
from test_tui_terminal_integration import FakeSession, select_row
from textual.widgets import DataTable

from debugpilot.tui.container_details import ContainerDetails
from debugpilot.tui.execution_console import ExecutionConsole
from debugpilot.tui.terminal_view import TerminalPane


@pytest.mark.asyncio
async def test_container_logs_navigation_preserves_pinned_session(
    tmp_path, monkeypatch
):
    app, docker, made, _workspace, service, launch, compose, original = central_app(
        tmp_path, monkeypatch
    )
    docker.inventory.append(item("actual-worker-29", "demo", "worker"))
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: docker.requested == 2 and table.row_count == 3)
        console = app.query_one(ExecutionConsole)
        logs = app.query_one("#logs-panel")
        # A selected profile shows the project overview in the right-hand area.
        before = app.query_one("#project-overview").region
        assert made == [] and not console.expanded
        await select_row(app, pilot, "#launch-profiles",
                         "profile-child:profile:Central:actual-api-17", "actual-api-17")
        await pilot.press("c")
        await pilot.pause()
        active = [pane for pane in app.query(TerminalPane) if pane.active]
        assert len(active) == 1
        pane = active[0]
        assert pane.parent.id == "container-shell"
        shell = pane.parent
        assert shell.parent.id == "right-panel" and shell.region == before
        assert not logs.display and not console.expanded and app.focused is pane
        assert made[0].container[:3] == (
            docker.inventory[0], "unix:///tmp/fixture-docker.sock", service.resolve()
        )
        await pilot.press("x", "o", "escape")
        assert made[0].writes == ["x", "o"] and app.focused is table
        await pilot.click("#container-shell-logs")
        await pilot.pause()
        assert logs.display and not shell.display and pane.active and not made[0].closed
        table.focus()
        await pilot.press("c")
        await pilot.pause()
        assert shell.display and pane.active and len(made) == 1
        await pilot.press("escape", "ctrl+l")
        await pilot.pause()
        assert logs.display and not shell.display and pane.active
        table.focus()
        await select_row(app, pilot, "#launch-profiles",
                         "profile-child:profile:Central:actual-worker-29", "actual-worker-29")
        assert pane.context.container.id == "actual-api-17" and len(made) == 1
        assert_files_unchanged(launch, compose, original)
    assert all(session.closed for session in made)


@pytest.mark.asyncio
async def test_view_switch_keeps_host_below_and_only_one_session(
    tmp_path, monkeypatch
):
    app, docker, made, _workspace, service, launch, compose, original = central_app(
        tmp_path, monkeypatch
    )
    docker.inventory.append(item("actual-worker-29", "demo", "worker"))
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: docker.requested == 2 and table.row_count == 3)
        console = app.query_one(ExecutionConsole)
        logs = app.query_one("#logs-panel")
        # A selected profile shows the project overview in the right-hand area.
        before = app.query_one("#project-overview").region
        assert made == [] and not console.expanded
        await select_row(app, pilot, "#launch-profiles",
                         "profile-child:profile:Central:actual-api-17", "actual-api-17")
        await pilot.press("c")
        await pilot.pause()
        active = [pane for pane in app.query(TerminalPane) if pane.active]
        assert len(active) == 1
        pane = active[0]
        assert pane.parent.id == "container-shell"
        shell = pane.parent
        assert shell.parent.id == "right-panel" and shell.region == before
        assert not logs.display and not console.expanded and app.focused is pane
        assert made[0].container[:3] == (
            docker.inventory[0], "unix:///tmp/fixture-docker.sock", service.resolve()
        )
        await pilot.press("escape")
        await select_row(app, pilot, "#launch-profiles",
                         "profile-child:profile:Central:actual-worker-29", "actual-worker-29")
        assert pane.context.container.id == "actual-api-17" and len(made) == 1
        await pilot.press("t")
        await pilot.pause()
        host = app.query_one("#terminal-pane", TerminalPane)
        assert made[0].closed and len(made) == 2
        # Closing the container shell returns to the selection's default details view.
        details = app.query_one(ContainerDetails)
        host_dock = app.query_one("#host-terminal")
        assert host.active and not pane.active and host_dock.display and details.display
        assert not logs.display
        assert host.parent is host_dock and app.focused is host
        assert made[1].host[0] == service.resolve()
        await pilot.press("escape", "c")
        await pilot.pause()
        assert made[1].closed and len(made) == 3 and pane.active and not host.active
        assert made[2].container[0].id == "actual-worker-29"
        assert shell.display and not logs.display
        await pilot.click("#container-terminal-close")
        await pilot.pause()
        assert made[2].closed and not pane.active and details.display and not shell.display
        assert not logs.display
        assert sum(view.active for view in app.query(TerminalPane)) == 0
        assert_files_unchanged(launch, compose, original)
    assert all(session.closed for session in made)


@pytest.mark.asyncio
async def test_close_during_view_switch_joins_prior_cleanup_without_starting_c(
    tmp_path, monkeypatch
):
    app, docker, _made, _workspace, _service, launch, compose, original = central_app(
        tmp_path, monkeypatch
    )
    entered, release = asyncio.Event(), asyncio.Event()
    made = []

    class SlowClose(FakeSession):
        async def close_session(self):
            if hasattr(self, "host") and not self.closed:
                entered.set()
                await release.wait()
            await super().close_session()

    def factory(**callbacks):
        session = SlowClose(**callbacks)
        made.append(session)
        return session

    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", factory)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: docker.requested == 2)
        await select_row(app, pilot, "#launch-profiles",
                         "profile-child:profile:Central:actual-api-17", "actual-api-17")
        await pilot.press("t", "escape", "c")
        await asyncio.wait_for(entered.wait(), 1)
        try:
            active = app.query_one("#container-shell")
            assert active.display
            closing = asyncio.create_task(app.run_action("close_terminal"))
            await asyncio.sleep(0)
        finally:
            release.set()
        await asyncio.wait_for(closing, 2)
        await pilot.pause()
        assert len(made) == 1 and made[0].closed
        assert all(not pane.active for pane in app.query(TerminalPane))
        # The selected container's default details view returns, not the log panel.
        assert not active.display and app.query_one(ContainerDetails).display
        assert not app.query_one("#logs-panel").display
        assert_files_unchanged(launch, compose, original)
