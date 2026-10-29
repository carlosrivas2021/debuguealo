import asyncio

import pytest
from test_tui_compose import Service
from test_tui_grouping import Docker, item, select_key, until
from textual.widgets import Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import LogEntry
from debugpilot.docker.compose import ComposeProject, ComposeResult
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.log_viewer import LogViewer


class RunDocker(Docker):
    def __init__(self):
        super().__init__()
        self.inventory = [
            item("orders-api", "orders", "api"),
            item("orders-worker", "orders", "worker"),
            item("catalog-api", "catalog", "api"),
        ]
        self.ended = {c.id: asyncio.Event() for c in self.inventory}
        self.revision = 0
        self.options = []

    async def stream_logs(self, name, **options):
        self.opened.append(name)
        self.options.append(options)
        try:
            if not options.get("current_run"):
                yield LogEntry(text="previous execution")
            yield LogEntry(text=f"run {self.revision} startup")
            await self.ended[name].wait()
        finally:
            self.closed.append(name)

    def restart(self, plan):
        self.revision += 1
        for index, container in enumerate(self.inventory):
            if container.compose_project != plan.project.project_name:
                continue
            if plan.service is not None and container.compose_service != plan.service:
                continue
            self.ended[container.id].set()
            if plan.action == "rebuild":
                identity = container.id + "-new"
                self.inventory[index] = container.model_copy(update={"id": identity})
                self.ended[identity] = asyncio.Event()
            else:
                self.ended[container.id] = asyncio.Event()


class RestartService(Service):
    def __init__(self, docker, exit_code=0, blocked=False):
        super().__init__()
        self.docker, self.exit_code = docker, exit_code
        self.release = asyncio.Event()
        if not blocked:
            self.release.set()

    async def run(self, plan, *, confirmed=False):
        self.runs.append((plan, confirmed))
        await self.release.wait()
        if self.exit_code == 0:
            self.docker.restart(plan)
            await asyncio.sleep(0)
        return ComposeResult(self.exit_code, "Complete")


def make_app(tmp_path, monkeypatch, *, exit_code=0, blocked=False):
    (tmp_path / "compose.yaml").write_text("services: {}")
    docker = RunDocker()
    service = RestartService(docker, exit_code, blocked)
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    return app, docker, service


@pytest.mark.parametrize("key", ["r", "R"])
@pytest.mark.parametrize("target", ["container:orders-api", "project:orders"])
async def test_success_reconnects_current_execution_and_discards_stale_view(
    tmp_path, monkeypatch, key, target
):
    app, docker, service = make_app(tmp_path, monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        select_key(app, target)
        viewer = app.query_one(LogViewer)
        await until(pilot, lambda: bool(viewer.buffer.entries()))
        await pilot.press(key, "enter")
        await until(pilot, lambda: app._inline_task is not None and app._inline_task.done())
        await until(pilot, lambda: any("run 1 startup" in e.text for e in viewer.buffer.entries()))
        assert len(service.runs) == 1
        assert all("run 1 startup" in e.text for e in viewer.buffer.entries())
        assert all(options.get("current_run") for options in docker.options)
        assert "stream ended" not in str(app.query_one("#log-state", Static).render())
        if target.startswith("container:"):
            assert app.selected_container.compose_service == "api"
            assert app.selected_container.id == "orders-api" + ("-new" if key == "R" else "")
        else:
            assert app.selected_project == "orders" and app.selected_container is None
            assert {e.text for e in viewer.buffer.entries()} == {
                "[api] run 1 startup",
                "[worker] run 1 startup",
            }
        opened = len(docker.opened)
        await pilot.press("ctrl+r")
        await until(pilot, lambda: len(docker.opened) > opened)
        assert not any("previous execution" in e.text for e in viewer.buffer.entries())
    assert sorted(docker.closed) == sorted(docker.opened)


@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_or_cancelled_operation_preserves_current_stream(
    tmp_path, monkeypatch, cancel
):
    app, docker, _service = make_app(tmp_path, monkeypatch, exit_code=1, blocked=cancel)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        select_key(app, "container:orders-api")
        await until(pilot, lambda: docker.opened[-1] == "orders-api")
        viewer = app.query_one(LogViewer)
        await until(pilot, lambda: bool(viewer.buffer.entries()))
        before = viewer.buffer.entries()
        saved = app._compose_store.path.read_bytes()
        opened, closed = docker.opened.copy(), docker.closed.copy()
        await pilot.press("r", "enter")
        await until(pilot, lambda: app._inline_task is not None)
        if cancel:
            await pilot.press("escape")
        await until(pilot, lambda: app._inline_task.done())
        assert viewer.buffer.entries() == before
        assert docker.opened == opened and docker.closed == closed
        assert app._compose_store.path.read_bytes() == saved


async def test_completion_does_not_retarget_unrelated_selection(tmp_path, monkeypatch):
    app, docker, service = make_app(tmp_path, monkeypatch, blocked=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        select_key(app, "container:orders-api")
        await until(pilot, lambda: docker.opened[-1] == "orders-api")
        await pilot.press("r", "enter")
        await until(pilot, lambda: bool(service.runs))
        select_key(app, "container:catalog-api")
        await until(pilot, lambda: docker.opened[-1] == "catalog-api")
        count = len(docker.opened)
        service.release.set()
        await until(pilot, lambda: app._inline_task.done())
        assert app.selected_container.id == "catalog-api"
        assert len(docker.opened) == count


async def test_selecting_again_and_retrying_only_show_the_current_execution(tmp_path, monkeypatch):
    app, docker, _service = make_app(tmp_path, monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        viewer = app.query_one(LogViewer)
        for target in ("container:orders-api", "container:orders-worker", "container:orders-api"):
            opened = len(docker.opened)
            select_key(app, target)
            await until(pilot, lambda opened=opened: len(docker.opened) > opened)
            await until(pilot, lambda: bool(viewer.buffer.entries()))
            assert [e.text for e in viewer.buffer.entries()] == ["run 0 startup"]
        opened = len(docker.opened)
        await pilot.press("ctrl+r")
        await until(pilot, lambda: len(docker.opened) > opened)
        await until(pilot, lambda: bool(viewer.buffer.entries()))
        assert [e.text for e in viewer.buffer.entries()] == ["run 0 startup"]


async def test_temporary_stopped_state_does_not_lose_restart_target(tmp_path, monkeypatch):
    app, docker, service = make_app(tmp_path, monkeypatch, blocked=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(docker.opened))
        select_key(app, "container:orders-api")
        await until(pilot, lambda: docker.opened[-1] == "orders-api")
        await pilot.press("r", "enter")
        await until(pilot, lambda: bool(service.runs))
        index = next(i for i, c in enumerate(docker.inventory) if c.id == "orders-api")
        original = docker.inventory[index]
        docker.inventory[index] = original.model_copy(update={"state": "exited"})
        await until(pilot, lambda: app.selected_container is None)
        docker.inventory[index] = original
        service.release.set()
        await until(pilot, lambda: app._inline_task.done())
        await until(pilot, lambda: app.selected_container is not None)
        assert app.selected_container.id == "orders-api"
        await until(
            pilot,
            lambda: any(
                e.text == "run 1 startup" for e in app.query_one(LogViewer).buffer.entries()
            ),
        )
