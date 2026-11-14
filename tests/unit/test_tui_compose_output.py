import asyncio

import pytest
from launch_ui_helpers import save_remembered_profile
from test_tui_grouping import Docker, ready, select_key, until
from textual.widgets import DataTable, RichLog

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.docker.compose import ComposeProject, ComposeResult
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.log_viewer import LogViewer

MISSING = "Error response from daemon: No such image: alpine:3.22"


class StreamingService:
    def __init__(self):
        self.runs = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def capture_retry_environment(self, _plan):
        return "a" * 64

    def preview(self, project, action, service=None):
        return type(
            "Plan",
            (),
            {
                "project": project,
                "action": action,
                "service": service,
                "display": f"compose {action}",
            },
        )()

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
        self.runs.append((plan, confirmed, pull_missing, retry_fingerprint))
        if on_output is not None:
            on_output("progress [red]literal[/red]")
        self.started.set()
        if pull_missing:
            if on_output is not None:
                on_output("retry failed")
            return ComposeResult(1, "retry failed")
        await self.release.wait()
        if on_output is not None:
            on_output(MISSING)
        return ComposeResult(1, MISSING)


def create_app(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    service = StreamingService()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = Docker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    save_remembered_profile(app, "orders")
    return app, service, docker


@pytest.mark.parametrize("decision", ["enter-cancel", "accept"])
async def test_inline_compose_output_streams_and_uses_safe_inline_consent(
    tmp_path, monkeypatch, decision
):
    app, service, docker = create_app(tmp_path, monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        screen = app.screen
        select_key(app, "profile:Orders")
        await pilot.click("#compose-output-toggle")
        await pilot.press("r")
        await pilot.click("#inline-compose-confirm")
        await until(pilot, service.started.is_set)
        output = app._compose_outputs.get("orders")
        transcript = app.query_one("#compose-output-viewer", RichLog)
        await until(
            pilot,
            lambda: any("progress [red]literal[/red]" in line.text for line in transcript.lines),
        )
        assert app.screen is screen
        assert not app._compose_tasks["orders"].done()
        service.release.set()
        await until(
            pilot,
            lambda: "Download" in str(app.query_one("#inline-compose-message").render()),
        )
        await until(pilot, lambda: app.query_one("#inline-compose-cancel").has_focus)
        assert any(MISSING in entry.text for entry in output.entries())
        assert any("exited 1" in entry.text for entry in output.entries())
        if decision == "enter-cancel":
            await pilot.press("enter")
            await until(pilot, lambda: app._compose_tasks["orders"].done())
            assert len(service.runs) == 1
        else:
            await pilot.click("#inline-compose-confirm")
            await pilot.click("#inline-compose-confirm")
            await until(pilot, lambda: len(service.runs) == 2)
            await until(pilot, lambda: app._compose_tasks["orders"].done())
            assert service.runs[1][1:] == (True, True, "a" * 64)
            assert any("retry failed" in entry.text for entry in output.entries())
            assert any("retry exited 1" in entry.text for entry in output.entries())
        assert not any(
            "[Compose · Orders]" in entry.text
            for entry in app.query_one(LogViewer).buffer.entries()
        )
        assert app.screen is screen
        assert app.query_one("#inline-compose-confirm").label == "Confirm"
        assert not app.query_one("#inline-compose-confirm").disabled
        assert app.query_one("#inline-compose-cancel").label == "Cancel"
        assert not app.query_one("#inline-compose-cancel").disabled
        await until(pilot, lambda: app.query_one("#launch-profiles", DataTable).has_focus)


async def test_latest_compose_output_survives_same_profile_refresh_not_other_project(
    tmp_path, monkeypatch
):
    app, service, docker = create_app(tmp_path, monkeypatch)
    service.release.set()
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "profile:Orders")
        await pilot.click("#compose-output-toggle")
        await pilot.press("r")
        await pilot.click("#inline-compose-confirm")
        await until(
            pilot,
            lambda: "Download" in str(app.query_one("#inline-compose-message").render()),
        )
        output = app._compose_outputs.get("orders")
        await until(pilot, lambda: any(MISSING in entry.text for entry in output.entries()))
        retained = output.entries()
        app._show_inventory(list(app._inventory.values()), force=True)
        assert output.entries() == retained
        await pilot.press("enter")
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        select_key(app, "project:catalog")
        await until(pilot, lambda: app.selected_project == "catalog")
        await pilot.pause(0.25)
        assert not any(
            "[Compose · Orders]" in entry.text
            for entry in app.query_one(LogViewer).buffer.entries()
        )
        transcript = app.query_one("#compose-output-viewer", RichLog)
        assert not any(MISSING in line.text for line in transcript.lines)
        select_key(app, "profile:Orders")
        await until(pilot, lambda: any(MISSING in line.text for line in transcript.lines))
        assert any(MISSING in entry.text for entry in output.entries())
