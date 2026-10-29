import asyncio

import pytest
from test_tui_compose import Service
from test_tui_grouping import Docker, select_key, until
from textual.widgets import Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.docker.compose import ComposeProject
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


@pytest.mark.parametrize("key,action", [("r", "restart"), ("R", "rebuild")])
@pytest.mark.parametrize("target", ["container:orders-api", "project:orders"])
async def test_inline_confirmation_never_changes_screen(tmp_path, monkeypatch, key, action, target):
    (tmp_path / "compose.yaml").write_text("services: {}")
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        screen = app.screen
        select_key(app, target)
        await pilot.press(key)
        assert app.screen is screen
        assert app.query_one("#inline-compose").display
        assert app.query_one("#inline-compose").size.height <= 4
        message = str(app.query_one("#inline-compose-message", Static).render())
        assert "orders" in message
        assert ("all services" in message) == target.startswith("project:")
        assert not service.runs
        await pilot.press("escape")
        assert not app.query_one("#inline-compose").display
        assert not service.runs
        select_key(app, target)
        await pilot.press(key)
        assert app.screen is screen
        select_key(app, "project:catalog")
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(service.runs))
        plan, confirmed = service.runs[0]
        assert confirmed and plan.action == action
        assert plan.project.project_name == "orders"
        assert plan.service == (None if target.startswith("project:") else "api")
        assert app.screen is screen


async def test_running_inline_operation_rejects_overlap_and_cancels_cleanly(tmp_path, monkeypatch):
    class BlockingService(Service):
        def __init__(self):
            super().__init__()
            self.closed = asyncio.Event()

        async def run(self, plan, *, confirmed=False):
            self.runs.append((plan, confirmed))
            try:
                await asyncio.Event().wait()
            finally:
                self.closed.set()

    (tmp_path / "compose.yaml").write_text("services: {}")
    service = BlockingService()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        screen = app.screen
        select_key(app, "project:orders")
        await pilot.press("r")
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(service.runs))
        await pilot.click("#inline-compose-confirm")
        app.action_start_project()
        app.action_restart_selected()
        assert app.screen is screen and len(service.runs) == 1
        await pilot.click("#inline-compose-cancel")
        await until(pilot, service.closed.is_set)
        await until(pilot, lambda: app._inline_task.done())
        assert not app.query_one("#inline-compose").display


async def test_unknown_project_shortcut_stays_on_dashboard(monkeypatch):
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test() as pilot:
        await until(pilot, lambda: bool(docker.opened))
        screen = app.screen
        await pilot.press("r")
        assert app.screen is screen
        assert not service.runs and not service.previews


@pytest.mark.parametrize("key,action", [("r", "restart"), ("R", "rebuild")])
@pytest.mark.parametrize("target", ["container:orders-api", "project:orders"])
async def test_enter_immediately_after_shortcut_confirms_once(
    tmp_path, monkeypatch, key, action, target
):
    (tmp_path / "compose.yaml").write_text("services: {}")
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        screen = app.screen
        select_key(app, target)
        await pilot.press(key, "enter")
        await until(pilot, lambda: bool(service.runs))
        plan, confirmed = service.runs[0]
        assert confirmed and plan.action == action
        assert plan.project.project_name == "orders"
        assert plan.service == (None if target.startswith("project:") else "api")
        assert app.screen is screen
        await until(pilot, lambda: app._inline_task.done())
        await pilot.press("enter")
        assert len(service.runs) == 1
