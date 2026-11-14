import asyncio
import json

import pytest
from launch_ui_helpers import save_remembered_profile
from test_tui_compose import Service
from test_tui_grouping import Docker, ready, select_key, until
from textual.widgets import Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.docker.compose import ComposeProject, ComposeResult
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


@pytest.mark.parametrize("key,action", [("r", "recreate"), ("R", "rebuild")])
@pytest.mark.parametrize("target", ["container:orders-api", "project:orders"])
async def test_inline_confirmation_never_changes_screen(tmp_path, monkeypatch, key, action, target):
    (tmp_path / "compose.yaml").write_text("services: {}")
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    save_remembered_profile(app, "orders")
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        screen = app.screen
        select_key(app, "profile:Orders")
        await pilot.press(key)
        assert app.screen is screen
        assert app.query_one("#inline-compose").display
        assert app.query_one("#inline-compose").size.height <= 4
        message = str(app.query_one("#inline-compose-message", Static).render())
        assert "Orders" in message
        assert "all services" in message
        assert not service.runs
        await pilot.press("escape")
        assert not app.query_one("#inline-compose").display
        assert not service.runs
        select_key(app, "profile:Orders")
        await pilot.press(key)
        assert app.screen is screen
        # Changing raw selection invalidates a profile preview.
        select_key(app, "project:catalog")
        await until(pilot, lambda: not app.query_one("#inline-compose").display)
        assert not service.runs
        select_key(app, "profile:Orders")
        await pilot.press(key)
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(service.runs))
        plan, confirmed = service.runs[0]
        assert confirmed and plan.action == action
        assert plan.project.project_name == "orders"
        assert plan.service is None
        assert app.screen is screen


async def test_running_inline_operation_rejects_overlap_and_cancels_cleanly(tmp_path, monkeypatch):
    class BlockingService(Service):
        def __init__(self):
            super().__init__()
            self.closed = asyncio.Event()

        async def run(self, plan, *, confirmed=False, on_output=None):
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
    save_remembered_profile(app, "orders")
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        screen = app.screen
        select_key(app, "profile:Orders")
        await pilot.press("r")
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(service.runs))
        await pilot.click("#inline-compose-confirm")
        app.action_recreate_selected()
        app.action_build_selected()
        assert app.screen is screen and len(service.runs) == 1
        # The bar is freed on confirm (S3); Esc cancels the selected project's run (S5).
        assert not app.query_one("#inline-compose").display
        await pilot.press("escape")
        await until(pilot, service.closed.is_set)
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        assert not app.query_one("#inline-compose").display


async def test_unknown_project_shortcut_stays_on_dashboard(monkeypatch):
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test() as pilot:
        await until(pilot, lambda: ready(app))
        screen = app.screen
        await pilot.press("r")
        assert app.screen is screen
        assert not service.runs and not service.previews


@pytest.mark.parametrize("key,action", [("r", "recreate"), ("R", "rebuild")])
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
    save_remembered_profile(app, "orders")
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        screen = app.screen
        select_key(app, "profile:Orders")
        await pilot.press(key, "enter")
        await until(pilot, lambda: bool(service.runs))
        plan, confirmed = service.runs[0]
        assert confirmed and plan.action == action
        assert plan.project.project_name == "orders"
        assert plan.service is None
        assert app.screen is screen
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        await pilot.press("enter")
        assert len(service.runs) == 1


async def test_inline_failure_shows_literal_output_and_missing_image_consent(tmp_path, monkeypatch):
    class FailedService(Service):
        async def run(
            self,
            plan,
            *,
            confirmed=False,
            pull_missing=False,
            retry_fingerprint=None,
            on_output=None,
            retry_preflight=None,
        ):
            self.runs.append((plan, confirmed, pull_missing))
            return ComposeResult(
                1,
                "retry failed"
                if pull_missing
                else "Error response from daemon: No such image: alpine:3.22\n[red]literal[/red]",
            )

    (tmp_path / "compose.yaml").write_text("services: {}")
    service = FailedService()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    save_remembered_profile(app, "orders")
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        screen = app.screen
        select_key(app, "profile:Orders")
        await pilot.press("r", "enter")
        await until(
            pilot,
            lambda: "Download" in str(app.query_one("#inline-compose-message").render()),
        )
        assert app.screen is screen
        output = app._compose_outputs.get("orders")
        entries = output.entries()
        assert len(service.runs) == 1
        assert service.runs[0][1:] == (True, False)
        assert any("No such image: alpine:3.22" in entry.text for entry in entries)
        assert any("[red]literal[/red]" in entry.text for entry in entries)
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        assert len(service.runs) == 2
        assert service.runs[1][1:] == (True, True)
        assert any("retry failed" in entry.text for entry in output.entries())
        assert any("retry exited 1" in entry.text for entry in output.entries())
        assert app.screen is screen
        assert app.query_one("#launch-profiles").has_focus


@pytest.mark.parametrize("cancel", ["button", "escape"])
async def test_missing_image_consent_cancel_never_retries(tmp_path, monkeypatch, cancel):
    class FailedService(Service):
        async def run(
            self,
            plan,
            *,
            confirmed=False,
            pull_missing=False,
            retry_fingerprint=None,
            on_output=None,
            retry_preflight=None,
        ):
            self.runs.append((plan, confirmed, pull_missing))
            return ComposeResult(1, "Error response from daemon: No such image: alpine:3.22")

    (tmp_path / "compose.yaml").write_text("services: {}")
    service = FailedService()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    save_remembered_profile(app, "orders")
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        screen = app.screen
        select_key(app, "profile:Orders")
        await pilot.press("r", "enter")
        await until(
            pilot,
            lambda: "Download" in str(app.query_one("#inline-compose-message").render()),
        )
        assert app.screen is screen
        if cancel == "button":
            await pilot.click("#inline-compose-cancel")
        else:
            await pilot.press("escape")
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        assert len(service.runs) == 1
        assert app.query_one("#launch-profiles").has_focus


async def test_generic_failure_shows_output_without_download_action(tmp_path, monkeypatch):
    class FailedService(Service):
        async def run(
            self,
            plan,
            *,
            confirmed=False,
            pull_missing=False,
            retry_fingerprint=None,
            on_output=None,
            retry_preflight=None,
        ):
            self.runs.append((plan, confirmed, pull_missing))
            return ComposeResult(1, "registry authentication failed")

    (tmp_path / "compose.yaml").write_text("services: {}")
    service = FailedService()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    save_remembered_profile(app, "orders")
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        screen = app.screen
        select_key(app, "profile:Orders")
        await pilot.press("r", "enter")
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        output = app._compose_outputs.get("orders")
        assert app.screen is screen
        assert any(
            "registry authentication failed" in entry.text for entry in output.entries()
        )
        assert any("Compose exited 1" in entry.text for entry in output.entries())
        assert not app.query_one("#inline-compose").display
        assert len(service.runs) == 1


async def test_changed_profile_cancels_pending_download_retry(tmp_path, monkeypatch):
    class FailedService(Service):
        async def run(
            self,
            plan,
            *,
            confirmed=False,
            pull_missing=False,
            retry_fingerprint=None,
            on_output=None,
            retry_preflight=None,
        ):
            self.runs.append((plan, confirmed, pull_missing))
            return ComposeResult(1, "Error response from daemon: No such image: alpine:3.22")

    (tmp_path / "compose.yaml").write_text("services: {}")
    service = FailedService()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    save_remembered_profile(app, "orders")
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles))
        select_key(app, "profile:Orders")
        await pilot.press("r", "enter")
        await until(
            pilot,
            lambda: "Download" in str(app.query_one("#inline-compose-message").render()),
        )
        document = json.loads(app._launch_store.path.read_text())
        document["configurations"][0]["custom"] = "changed"
        app._launch_store.path.write_text(json.dumps(document))
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        assert len(service.runs) == 1
        assert app._inline_plan is None
        assert any(
            "retry cancelled" in entry.text.lower()
            for entry in app._compose_outputs.get("orders").entries()
        )


async def test_empty_failure_output_has_actionable_fallback(tmp_path, monkeypatch):
    class FailedService(Service):
        async def run(
            self,
            plan,
            *,
            confirmed=False,
            pull_missing=False,
            retry_fingerprint=None,
            on_output=None,
            retry_preflight=None,
        ):
            self.runs.append((plan, confirmed, pull_missing))
            return ComposeResult(9, "")

    (tmp_path / "compose.yaml").write_text("services: {}")
    service = FailedService()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    save_remembered_profile(app, "orders")
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "profile:Orders")
        await pilot.press("r", "enter")
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        entries = app._compose_outputs.get("orders").entries()
        assert any("Compose exited 9" in entry.text for entry in entries)
        assert not any("No output was retained" in entry.text for entry in entries)


async def test_retry_failure_is_shown_without_automatic_loop(tmp_path, monkeypatch):
    class FailedService(Service):
        async def run(
            self,
            plan,
            *,
            confirmed=False,
            pull_missing=False,
            retry_fingerprint=None,
            on_output=None,
            retry_preflight=None,
        ):
            self.runs.append((plan, confirmed, pull_missing))
            return ComposeResult(
                1,
                "Error response from daemon: No such image: alpine:3.22"
                if not pull_missing
                else "retry failed",
            )

    (tmp_path / "compose.yaml").write_text("services: {}")
    service = FailedService()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    save_remembered_profile(app, "orders")
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "profile:Orders")
        await pilot.press("r", "enter")
        await until(
            pilot,
            lambda: "Download" in str(app.query_one("#inline-compose-message").render()),
        )
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        assert len(service.runs) == 2
        entries = app._compose_outputs.get("orders").entries()
        assert any("retry failed" in entry.text for entry in entries)
        assert any("retry exited 1" in entry.text for entry in entries)
