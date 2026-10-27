import asyncio
from datetime import UTC, datetime

import pytest
from textual.widgets import Button, DataTable, Input, Select, Static, TextArea

from debugpilot.core.engine import DebugPilotEngine, EngineState
from debugpilot.core.models import ContainerInfo
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.compose_dialog import ComposeDialog


def item(identity, project=None, service=None, state="running"):
    return ContainerInfo(
        id=identity,
        name=identity,
        image="demo:local",
        state=state,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        compose_project=project,
        compose_service=service,
    )


async def until(pilot, condition):
    async with asyncio.timeout(3):
        while not condition():
            await pilot.pause(0.02)


class Docker:
    def __init__(self):
        self.inventory = [
            item(f"{project}-{service}", project, service)
            for project in ("catalog", "gateway", "orders")
            for service in ("api", "worker")
        ]
        self.inventory.append(item("standalone"))
        self.opened, self.closed = [], []

    async def list_containers(self):
        return self.inventory

    async def stream_logs(self, name, **_options):
        self.opened.append(name)
        try:
            await asyncio.Event().wait()
            yield
        finally:
            self.closed.append(name)


def select_key(app, key):
    table = app.query_one("#containers", DataTable)
    table.move_cursor(
        row=next(index for index, row in enumerate(table.ordered_rows) if row.key.value == key)
    )


async def test_projects_and_standalone_are_grouped_and_group_selection_closes_logs():
    docker = Docker()
    engine = DebugPilotEngine(Settings(), docker=docker)
    app = DebugPilotApp(engine, refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        table = app.query_one("#containers", DataTable)
        keys = [row.key.value for row in table.ordered_rows]
        assert keys == [
            "project:catalog",
            "container:catalog-api",
            "container:catalog-worker",
            "project:gateway",
            "container:gateway-api",
            "container:gateway-worker",
            "project:orders",
            "container:orders-api",
            "container:orders-worker",
            "standalone:",
            "container:standalone",
        ]
        select_key(app, "project:orders")
        await until(
            pilot,
            lambda: (
                app.selected_container is None
                and bool(docker.closed)
                and "select a service" in str(app.query_one("#log-state", Static).render()).lower()
            ),
        )
        assert app.selected_project == "orders"
        assert "select a service" in str(app.query_one("#log-state", Static).render()).lower()
        await pilot.press("ctrl+o")
        await until(pilot, lambda: isinstance(app.screen, ComposeDialog))
        assert app.screen.query_one("#compose-project", Input).value == "orders"
        assert app.screen.query_one("#compose-scope", Select).value == "project"
        assert app.screen.query_one("#compose-confirm", Button).disabled
        await pilot.press("escape")
        select_key(app, "container:gateway-api")
        await until(
            pilot,
            lambda: (
                app.selected_container is not None and app.selected_container.id == "gateway-api"
            ),
        )
        await pilot.press("ctrl+o")
        assert app.screen.query_one("#compose-project", Input).value == "gateway"
        assert app.screen.query_one("#compose-scope", Select).value == "service"
        assert app.screen.selected.compose_service == "api"
    assert engine.state == EngineState.CLOSED
    assert len(docker.closed) == len(docker.opened)


async def test_selection_identity_survives_refresh_then_disappears_without_wrong_stream():
    docker = Docker()
    engine = DebugPilotEngine(Settings(), docker=docker)
    app = DebugPilotApp(engine, refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        select_key(app, "container:orders-api")
        await until(pilot, lambda: docker.opened[-1] == "orders-api")
        opened = list(docker.opened)
        docker.inventory = list(reversed(docker.inventory))
        await pilot.pause(0.1)
        assert app.selected_container.id == "orders-api" and docker.opened == opened
        docker.inventory = [value for value in docker.inventory if value.id != "orders-api"]
        await until(
            pilot, lambda: app.selected_container is None and app.selected_project == "orders"
        )
        assert docker.opened == opened
        docker.inventory = [
            value for value in docker.inventory if value.compose_project != "orders"
        ]
        await until(pilot, lambda: app.selected_project != "orders")
        assert app.selected_container is None and docker.opened == opened
        select_key(app, "container:standalone")
        await until(
            pilot,
            lambda: (
                app.selected_container is not None and app.selected_container.id == "standalone"
            ),
        )
        assert app.selected_project is None
        await pilot.press("ctrl+o")
        assert app.screen.query_one("#compose-project", Input).value == ""
        assert app.screen.query_one("#compose-scope", Select).value == "project"


async def test_group_preview_cannot_retarget_a_different_project(tmp_path):
    from test_tui_compose import Service
    from textual.app import App

    (tmp_path / "compose.yaml").write_text("services: {}")
    service, app = Service(), App()
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(ComposeDialog(service, None, selected_project="orders"))
        await pilot.pause()
        dialog = app.screen
        dialog.query_one("#compose-workspace", Input).value = str(tmp_path)
        dialog.query_one("#compose-project", Input).value = "gateway"
        dialog.query_one(TextArea).text = "compose.yaml"
        await pilot.pause()
        await pilot.click("#compose-preview")
        await pilot.pause()
        assert not service.previews and not service.runs
        assert dialog.query_one("#compose-confirm", Button).disabled


async def test_group_restart_previews_and_confirms_only_the_selected_project(tmp_path):
    from test_tui_compose import Service
    from textual.app import App

    (tmp_path / "compose.yaml").write_text("services: {}")
    service, app = Service(), App()
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(
            ComposeDialog(service, None, selected_project="orders", initial_action="restart")
        )
        await pilot.pause()
        dialog = app.screen
        dialog.query_one("#compose-workspace", Input).value = str(tmp_path)
        await pilot.pause()
        await pilot.click("#compose-preview")
        await until(pilot, lambda: dialog.plan is not None)
        assert service.previews[-1][0].project_name == "orders"
        assert service.previews[-1][1:] == ("restart", None)
        assert not service.runs
        await pilot.click("#compose-confirm")
        await until(pilot, lambda: bool(service.runs))
        plan, confirmed = service.runs[0]
        assert confirmed and plan.project.project_name == "orders" and plan.service is None


@pytest.mark.parametrize("target", ["container:orders-api", "project:orders"])
async def test_r_requests_restart_for_selected_target_without_execution(target, monkeypatch):
    from test_tui_compose import Service

    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        select_key(app, target)
        await until(pilot, lambda: app.selected_project == "orders")
        await pilot.press("r")
        assert isinstance(app.screen, ComposeDialog)
        assert app.screen.query_one("#compose-action", Select).value == "restart"
        assert app.screen.query_one("#compose-project", Input).value == "orders"
        assert app.screen.query_one("#compose-scope", Select).value == (
            "project" if target.startswith("project:") else "service"
        )
        assert app.screen.query_one("#compose-confirm", Button).disabled
        assert not service.previews and not service.runs


@pytest.mark.parametrize("key", ["R", "shift+r"])
@pytest.mark.parametrize("target", ["container:gateway-api", "project:gateway"])
async def test_shift_r_requests_rebuild_and_typing_never_runs_actions(key, target, monkeypatch):
    from test_tui_compose import Service

    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        app.query_one("#filter-logs", Input).focus()
        await pilot.press("r", "R")
        assert app.query_one("#filter-logs", Input).value == "rR"
        assert not isinstance(app.screen, ComposeDialog)
        app.query_one("#containers", DataTable).focus()
        select_key(app, target)
        await until(pilot, lambda: app.selected_project == "gateway")
        await pilot.press(key)
        assert isinstance(app.screen, ComposeDialog)
        assert app.screen.query_one("#compose-action", Select).value == "rebuild"
        assert app.screen.query_one("#compose-scope", Select).value == (
            "project" if target.startswith("project:") else "service"
        )
        app.screen.query_one(TextArea).focus()
        await pilot.press("r", "R")
        assert app.screen.query_one(TextArea).text.startswith("rR")
        assert app.screen.query_one("#compose-confirm", Button).disabled
        assert not service.previews and not service.runs


async def test_context_shortcuts_refuse_standalone_and_ctrl_r_retries_logs():
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        select_key(app, "container:standalone")
        await until(pilot, lambda: docker.opened[-1] == "standalone")
        await pilot.press("r", "R")
        assert not isinstance(app.screen, ComposeDialog)
        previous = len(docker.opened)
        await pilot.press("ctrl+r")
        await until(pilot, lambda: len(docker.opened) == previous + 1)
        assert docker.opened[-1] == "standalone"


async def test_context_shortcuts_refuse_an_empty_inventory():
    docker = Docker()
    docker.inventory = []
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("r", "R")
        assert app.selected_container is None and app.selected_project is None
        assert not isinstance(app.screen, ComposeDialog)
        assert not docker.opened
