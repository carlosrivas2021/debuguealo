"""Central-profile terminal routing and complete dock visibility, with fake sessions."""

import json

import pytest
from test_tui_grouping import item, until
from test_tui_inventory_scroll import ControlledInventory
from test_tui_terminal_integration import FakeSession, select_row
from textual.widgets import DataTable, RichLog, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import LogEntry
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.execution_console import ExecutionConsole
from debugpilot.tui.terminal_view import TerminalPane


async def click_output_toggle(pilot):
    """Click the output card toggle once its position has settled after a resize."""
    await pilot.pause()
    await pilot.click("#compose-output-toggle")
    await pilot.pause()

def central_app(tmp_path, monkeypatch, *, mode="central"):
    workspace = tmp_path / "workspace"
    service = workspace / "service"
    service.mkdir(parents=True)
    compose = service / "compose.yaml"
    compose.write_text("services: {}\n")
    launch = tmp_path / "config" / "launch.json"
    launch.parent.mkdir()
    configurations = [{
        "name": "Central", "type": "docker-compose", "projectName": "demo",
        "workspaceFolder": str(workspace), "cwd": "${workspaceFolder}/service",
        "files": ["compose.yaml"],
    }]
    if mode == "missing":
        configurations = []
    elif mode == "invalid":
        configurations[0]["cwd"] = "${workspaceFolder}/../outside"
    launch.write_text(json.dumps({"version": 1, "configurations": configurations}))
    monkeypatch.setattr("debugpilot.storage.launch_profiles.config_path",
                        lambda: launch.parent / "config.toml")
    if mode == "local":
        launch = workspace / ".debugpilot" / "launch.json"
        launch.parent.mkdir()
        launch.write_text(json.dumps({"version": 1, "configurations": configurations}))
    original = (launch.read_bytes(), compose.read_bytes())
    made = []

    def factory(**callbacks):
        session = FakeSession(**callbacks)
        made.append(session)
        return session

    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", factory)
    docker = ControlledInventory()
    docker.inventory = [item("actual-api-17", "demo", "api")]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(docker_endpoint="unix:///tmp/fixture-docker.sock"),
                         docker=docker),
        workspace=workspace if mode == "local" else None, refresh_interval=0.05,
    )
    return app, docker, made, workspace, service, launch, compose, original


def assert_files_unchanged(launch, compose, original):
    assert (launch.read_bytes(), compose.read_bytes()) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["h", "c"])
async def test_central_profile_opens_exact_context_and_reveals_hidden_console(
    tmp_path, monkeypatch, key
):
    app, docker, made, workspace, service, launch, compose, original = central_app(
        tmp_path, monkeypatch
    )
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: docker.requested == 2 and table.row_count == 2)
        child = "profile-child:profile:Central:actual-api-17"
        await select_row(app, pilot, "#launch-profiles", child, "actual-api-17")
        assert made == []
        assert not app.query_one(ExecutionConsole).expanded
        await pilot.press(key)
        await pilot.pause()
        assert len(made) == 1
        pane = app.query_one("#terminal-pane" if key == "h" else "#container-terminal-pane",
                             TerminalPane)
        console = app.query_one(ExecutionConsole)
        owner = app.query_one("#host-terminal" if key == "h" else "#container-shell")
        assert pane.active and owner.display and pane.region.height > 0
        assert app.focused is pane
        await pilot.press("x", "o")
        assert made[0].writes == ["x", "o"] and owner.display
        if key == "h":
            assert made[0].host[0] == service.resolve()
            assert pane.context.kind == "host" and pane.context.container is None
        else:
            assert made[0].container[:3] == (
                docker.inventory[0], "unix:///tmp/fixture-docker.sock", service.resolve()
            )
            assert pane.context.container.id == "actual-api-17"
        context = pane.context
        await pilot.press("escape")
        if key == "h":
            # The host shell is independent of the output card's own toggle.
            await click_output_toggle(pilot)
            await pilot.pause()
            assert console.expanded and owner.display and pane.active and not made[0].closed
        else:
            await pilot.click("#container-shell-logs")
            await pilot.pause()
            assert not owner.display and pane.active and not made[0].closed
            app.query_one("#launch-profiles", DataTable).focus()
            await pilot.press("c")
            await pilot.pause()
        assert owner.display and pane.active and pane.context == context
        assert len(made) == 1 and not made[0].closed
        await pilot.click("#terminal-close" if key == "h" else "#container-terminal-close")
        await pilot.pause()
        assert made[0].closed and not pane.active
        assert not owner.display if key == "h" else app.query_one("#logs-panel").display
        assert_files_unchanged(launch, compose, original)
    assert made[0].closed


@pytest.mark.asyncio
async def test_minimize_button_collapses_console_and_expand_restores_transcript(
    tmp_path, monkeypatch
):
    app, docker, made, _workspace, _service, launch, compose, original = central_app(
        tmp_path, monkeypatch
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: docker.requested == 2)
        console = app.query_one(ExecutionConsole)
        await click_output_toggle(pilot)
        await pilot.pause()
        console.append(LogEntry(text="[FIXTURE] Compose exited 0.", severity="info"))
        await pilot.pause()
        viewer = app.query_one("#compose-output-viewer", RichLog)
        lines = tuple(viewer.lines)
        height = console.region.height
        dashboard = app.query_one("#dashboard")
        initial = dashboard.region.height
        assert height > 0 and lines
        assert app.query_one("#sidebar").region.height == initial
        await click_output_toggle(pilot)
        await pilot.pause()
        assert not console.expanded and console.region.height <= 3
        assert dashboard.region.height == initial
        assert app.focused is app.query_one("#launch-profiles", DataTable)
        assert tuple(viewer.lines) == lines and made == []
        await click_output_toggle(pilot)
        await pilot.pause()
        assert console.expanded and dashboard.region.height == initial
        assert tuple(viewer.lines) == lines and made == []
        await click_output_toggle(pilot)
        await pilot.pause()
        assert not console.expanded and dashboard.region.height == initial
        assert_files_unchanged(launch, compose, original)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "invalid", "local"])
async def test_context_refusals_and_explicit_local_workspace_are_preserved(
    tmp_path, monkeypatch, mode
):
    app, docker, made, workspace, _service, launch, compose, original = central_app(
        tmp_path, monkeypatch, mode=mode
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: docker.requested == 2)
        app.query_one("#launch-profiles", DataTable).focus()
        await pilot.press("h")
        await pilot.pause()
        if mode == "local":
            assert len(made) == 1 and made[0].host[0] == workspace.resolve()
            assert app.query_one("#terminal-pane", TerminalPane).active
        else:
            assert made == [] and not app.query_one("#terminal-pane", TerminalPane).active
            message = str(app.query_one("#terminal-context", Static).render())
            assert "Terminal unavailable:" in message
        assert_files_unchanged(launch, compose, original)
    assert all(session.closed for session in made)
