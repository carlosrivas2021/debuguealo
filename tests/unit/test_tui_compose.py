from types import SimpleNamespace

from textual.app import App
from textual.widgets import Button, Input, Select, TextArea

from debugpilot.core.models import ContainerInfo
from debugpilot.docker.compose import ComposeResult
from debugpilot.tui.compose_dialog import ComposeDialog


class Service:
    def __init__(self):
        self.previews = []
        self.runs = []

    def preview(self, project, action, service=None):
        self.previews.append((project, action, service))
        return SimpleNamespace(
            project=project,
            action=action,
            service=service,
            display=f"docker compose {action} {service or 'ALL'}",
        )

    async def capture_retry_environment(self, plan):
        return "a" * 64

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
        self.runs.append((plan, confirmed))
        return ComposeResult(0, "Complete")


async def open_dialog(app, service, project, selected):
    dialog = ComposeDialog(service, selected)
    app.push_screen(dialog)
    return dialog


async def test_compose_requires_preview_and_explicit_confirmation(tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}")
    service = Service()
    app = App()
    async with app.run_test(size=(120, 40)) as pilot:
        dialog = await open_dialog(app, service, tmp_path, None)
        await pilot.pause()
        assert dialog.query_one("#compose-confirm", Button).disabled
        dialog.query_one("#compose-workspace", Input).value = str(tmp_path)
        dialog.query_one("#compose-project", Input).value = "demo"
        dialog.query_one(TextArea).text = "compose.yaml"
        await pilot.pause()
        await pilot.click("#compose-preview")
        await pilot.pause(0.2)
        assert not service.runs
        assert not dialog.query_one("#compose-confirm", Button).disabled
        assert service.previews[0][0].files == ((tmp_path / "compose.yaml").resolve(),)
        assert service.previews[0][2] is None
        await pilot.click("#compose-confirm")
        await pilot.pause()
        assert len(service.runs) == 1 and service.runs[0][1] is True
        assert dialog.query_one("#compose-confirm", Button).disabled


async def test_scope_and_changed_form_invalidate_confirmation(tmp_path):
    from datetime import UTC, datetime

    (tmp_path / "compose.yaml").write_text("services: {}")
    selected = ContainerInfo(
        id="id",
        name="demo-api-1",
        image="demo",
        state="running",
        created_at=datetime.now(UTC),
        compose_project="demo",
        compose_service="api",
    )
    service, app = Service(), App()
    async with app.run_test(size=(120, 40)) as pilot:
        dialog = await open_dialog(app, service, tmp_path, selected)
        await pilot.pause()
        dialog.query_one("#compose-workspace", Input).value = str(tmp_path)
        dialog.query_one(TextArea).text = "compose.yaml"
        await pilot.pause()
        await pilot.click("#compose-preview")
        await pilot.pause(0.2)
        assert service.previews[-1][2] == "api"
        dialog.query_one("#compose-action", Select).value = "restart"
        await pilot.pause()
        assert dialog.query_one("#compose-confirm", Button).disabled
        assert not service.runs
        await pilot.press("escape")
        assert not service.runs
