"""Concurrent Compose runs keep one bounded output buffer per Compose project."""

import asyncio
import json

import pytest
from test_tui_grouping import ready, select_key, until
from test_tui_stop import StopDocker
from textual.widgets import RichLog, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import LogEntry
from debugpilot.docker.compose import ComposeProject, ComposeResult
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.compose_output import ProjectOutputBuffers

MISSING = "Error response from daemon: No such image: alpine:3.22"


class ProjectService:
    """Fake Compose CLI whose runs are released per project."""

    def __init__(self, *, missing=(), released=()):
        self.runs: list[tuple[str, bool]] = []
        self.previews: list[str] = []
        self.started: dict[str, asyncio.Event] = {}
        self.release: dict[str, asyncio.Event] = {}
        self.cancelled: set[str] = set()
        self.missing = set(missing)
        for project in released:
            self.gate(project).set()

    def gate(self, project):
        return self.release.setdefault(project, asyncio.Event())

    def began(self, project):
        return self.started.setdefault(project, asyncio.Event())

    def preview(self, project, action, service=None):
        self.previews.append(project.project_name)
        return type(
            "Plan",
            (),
            {"project": project, "action": action, "service": service, "display": action},
        )()

    async def capture_retry_environment(self, _plan):
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
        project = plan.project.project_name
        self.runs.append((project, pull_missing))
        on_output(f"{project} progress")
        self.began(project).set()
        if pull_missing:
            if retry_preflight is not None and not retry_preflight():
                return ComposeResult(1, "preflight refused")
            on_output(f"{project} pulled")
            return ComposeResult(0, f"{project} pulled")
        try:
            await self.gate(project).wait()
        except asyncio.CancelledError:
            self.cancelled.add(project)
            raise
        if project in self.missing:
            on_output(MISSING)
            return ComposeResult(1, MISSING)
        on_output(f"{project} done")
        return ComposeResult(0, f"{project} done")


def create_app(tmp_path, monkeypatch, service, profiles=("orders", "catalog"), docker=None):
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: service)
    docker = docker or StopDocker()
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    for project in profiles:
        app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), project))
    path = tmp_path / ".debugpilot" / "launch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "configurations": [
                    {
                        "name": project.capitalize(),
                        "type": "docker-compose",
                        "projectName": project,
                        "cwd": "${workspaceFolder}",
                        "files": ["compose.yaml"],
                    }
                    for project in profiles
                ],
            }
        )
    )
    return app, docker


def output(app) -> str:
    return "\n".join(line.text for line in app.query_one("#compose-output-viewer", RichLog).lines)


def buffered(app, project) -> str:
    buffer = app._compose_outputs.get(project)
    return "\n".join(entry.text for entry in buffer.entries()) if buffer else ""


def message(app) -> str:
    return str(app.query_one("#inline-compose-message", Static).render())


def notices(app) -> list[str]:
    return [item.message for item in app._notifications]


async def expand_output(pilot):
    await pilot.pause()
    await pilot.click("#compose-output-toggle")
    await pilot.pause()


async def start(app, pilot, service, key, project):
    select_key(app, key)
    await until(pilot, lambda: app._selection_key == key)
    await pilot.press("r")
    assert app.query_one("#inline-compose").display
    await pilot.click("#inline-compose-confirm")
    await until(pilot, service.began(project).is_set)


async def test_two_projects_recreate_concurrently_with_separate_output(tmp_path, monkeypatch):
    service = ProjectService()
    app, _docker = create_app(tmp_path, monkeypatch, service)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles) and ready(app))
        await expand_output(pilot)
        await start(app, pilot, service, "profile:Orders", "orders")
        # The bar is free right after confirming, while the run continues.
        assert not app.query_one("#inline-compose").display
        await start(app, pilot, service, "profile:Catalog", "catalog")
        assert not app.query_one("#inline-compose").display
        assert service.runs == [("orders", False), ("catalog", False)]
        await until(pilot, lambda: "[Compose · Catalog] catalog progress" in output(app))
        assert "orders progress" not in output(app)
        select_key(app, "profile:Orders")
        await until(pilot, lambda: "[Compose · Orders] orders progress" in output(app))
        assert "catalog" not in output(app)
        # A container row of the project shows the same project buffer.
        select_key(app, "profile-child:profile:Orders:orders-api")
        await until(pilot, lambda: app._selection_key.startswith("profile-child:"))
        await until(pilot, lambda: "[Compose · Orders] orders progress" in output(app))
        service.gate("catalog").set()
        await until(pilot, lambda: app._compose_tasks["catalog"].done())
        await pilot.pause(0.1)
        assert "catalog done" not in output(app)
        assert not app._compose_tasks["orders"].done()
        select_key(app, "profile:Catalog")
        await until(pilot, lambda: "[Compose · Catalog] catalog done" in output(app))
        assert "[Compose · Catalog] Compose exited 0." in output(app)
        assert "orders" not in output(app)
        service.gate("orders").set()
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        # A new Orders run clears only the Orders buffer.
        await start(app, pilot, service, "profile:Orders", "orders")
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        await until(pilot, lambda: "Compose exited 0" in output(app))
        assert output(app).count("[Compose · Orders] Starting") == 1
        assert "catalog" not in output(app)
        select_key(app, "profile:Catalog")
        await until(pilot, lambda: "[Compose · Catalog] catalog done" in output(app))
        assert output(app).count("[Compose · Catalog] Starting") == 1


async def test_second_run_of_the_same_project_is_rejected(tmp_path, monkeypatch):
    service = ProjectService()
    app, _docker = create_app(tmp_path, monkeypatch, service)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles) and ready(app))
        await start(app, pilot, service, "profile:Orders", "orders")
        previews = list(service.previews)
        await pilot.press("r")
        await pilot.press("R")
        assert not app.query_one("#inline-compose").display
        assert service.previews == previews
        assert service.runs == [("orders", False)]
        assert "A Compose operation is already running for orders." in notices(app)
        # Other projects stay usable.
        await start(app, pilot, service, "profile:Catalog", "catalog")
        assert service.runs == [("orders", False), ("catalog", False)]
        service.gate("orders").set()
        service.gate("catalog").set()
        await until(pilot, lambda: all(task.done() for task in app._compose_tasks.values()))


async def test_missing_image_consent_waits_for_a_busy_bar_and_stays_bound(tmp_path, monkeypatch):
    service = ProjectService(missing={"orders"}, released={"catalog"})
    service.gate("catalog").clear()
    app, _docker = create_app(
        tmp_path, monkeypatch, service, profiles=("orders", "catalog", "gateway")
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles) and ready(app))
        await expand_output(pilot)
        await start(app, pilot, service, "profile:Orders", "orders")
        select_key(app, "profile:Catalog")
        await pilot.press("r")
        assert "Catalog" in message(app)
        service.gate("orders").set()
        await until(pilot, lambda: "Compose exited 1" in buffered(app, "orders"))
        await pilot.pause(0.2)
        # The consent waits; the pending Catalog preview is not overwritten.
        assert app.query_one("#inline-compose").display
        assert "Recreate Catalog" in message(app)
        await pilot.click("#inline-compose-confirm")
        await until(pilot, service.began("catalog").is_set)
        await until(pilot, lambda: "(orders). Download missing images" in message(app))
        assert app.query_one("#inline-compose-confirm").label == "Download and retry"
        # A new preview never clobbers the pending consent.
        select_key(app, "profile:Gateway")
        await until(pilot, lambda: app.selected_project == "gateway")
        await pilot.press("r")
        assert "(orders). Download missing images" in message(app)
        assert "gateway" not in service.previews
        assert "Answer the pending download prompt first." in notices(app)
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: ("orders", True) in service.runs)
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        assert not app.query_one("#inline-compose").display
        # The retry ran for Orders' own plan while Catalog keeps running.
        assert service.runs == [("orders", False), ("catalog", False), ("orders", True)]
        assert not app._compose_tasks["catalog"].done()
        orders = buffered(app, "orders")
        assert "[Compose · Orders] orders pulled" in orders
        assert "[Compose · Orders] Compose retry exited 0." in orders
        assert "catalog" not in orders
        assert "orders" not in output(app)
        service.gate("catalog").set()
        await until(pilot, lambda: app._compose_tasks["catalog"].done())


async def test_escape_cancels_only_the_selected_projects_run(tmp_path, monkeypatch):
    service = ProjectService()
    app, _docker = create_app(tmp_path, monkeypatch, service)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles) and ready(app))
        await expand_output(pilot)
        await start(app, pilot, service, "profile:Orders", "orders")
        await start(app, pilot, service, "profile:Catalog", "catalog")
        await pilot.press("escape")
        await until(pilot, lambda: app._compose_tasks["catalog"].done())
        assert service.cancelled == {"catalog"}
        assert not app._compose_tasks["orders"].done()
        await until(pilot, lambda: "Compose operation stopped by user" in output(app))
        select_key(app, "profile:Orders")
        await until(pilot, lambda: "orders progress" in output(app))
        assert "stopped by user" not in output(app)
        service.gate("orders").set()
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        await until(pilot, lambda: "[Compose · Orders] Compose exited 0." in output(app))
        assert service.cancelled == {"catalog"}


def test_project_buffers_evict_the_oldest_but_never_a_running_project():
    running = {"p0"}
    buffers = ProjectOutputBuffers(max_projects=3, protected=running.__contains__)
    for project in ("p0", "p1", "p2"):
        buffers.append(project, LogEntry(stream="combined", text=project))
    buffers.touch("p1")
    buffers.append("p3", LogEntry(stream="combined", text="p3"))
    # p0 is the oldest but running; p2 is the least recently written or viewed.
    assert buffers.projects() == ("p0", "p1", "p3")
    buffers.reset("p4")
    assert buffers.projects() == ("p0", "p3", "p4")
    assert [entry.text for entry in buffers.get("p0").entries()] == ["p0"]
    assert buffers.get("p2") is None
    buffers.append("p3", LogEntry(stream="combined", text="again"))
    buffers.reset("p3")
    assert buffers.get("p3").entries() == ()
    assert buffers.get("p0").max_entries == 1000
    assert buffers.get("p0").max_bytes == 1024 * 1024


async def test_app_keeps_eight_project_buffers_and_never_evicts_a_running_run(
    tmp_path, monkeypatch
):
    projects = [f"p{index}" for index in range(10)]
    service = ProjectService(released=projects[1:])
    app, _docker = create_app(tmp_path, monkeypatch, service, profiles=projects)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_profiles) == 10 and ready(app))
        await expand_output(pilot)
        await start(app, pilot, service, "profile:P0", "p0")
        for project in projects[1:]:
            await start(app, pilot, service, f"profile:{project.capitalize()}", project)
            await until(pilot, lambda project=project: app._compose_tasks[project].done())
        assert len(app._compose_outputs.projects()) == 8
        select_key(app, "profile:P1")
        await until(pilot, lambda: app.selected_project == "p1")
        await pilot.pause(0.2)
        assert "[Compose · P1]" not in output(app)
        select_key(app, "profile:P0")
        await until(pilot, lambda: "[Compose · P0] p0 progress" in output(app))
        select_key(app, "profile:P9")
        await until(pilot, lambda: "[Compose · P9] p9 done" in output(app))
        service.gate("p0").set()
        await until(pilot, lambda: app._compose_tasks["p0"].done())


async def test_stop_is_refused_for_a_project_being_recreated(tmp_path, monkeypatch):
    service = ProjectService()
    app, docker = create_app(tmp_path, monkeypatch, service, profiles=("orders",))
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles) and ready(app))
        await start(app, pilot, service, "profile:Orders", "orders")
        await pilot.press("s")
        assert not app.query_one("#inline-compose").display
        select_key(app, "profile-child:profile:Orders:orders-api")
        await until(pilot, lambda: app._selection_key.startswith("profile-child:"))
        await pilot.press("s")
        assert not app.query_one("#inline-compose").display
        assert "orders is being recreated; wait for it to finish." in notices(app)
        # Credential refresh stays exclusive with Compose runs.
        await pilot.press("a")
        assert not app.query_one("#inline-compose").display
        assert "An operation is already running." in notices(app)
        # Containers of other projects can still be stopped.
        select_key(app, "container:gateway-api")
        await pilot.press("s")
        assert app.query_one("#inline-compose").display
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(docker.stops))
        assert docker.stops == [(("gateway-api",), True, 10)]
        assert not app._compose_tasks["orders"].done()
        service.gate("orders").set()
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        await until(pilot, lambda: not app._stop_tasks)


@pytest.mark.parametrize(("key", "action"), [("r", "recreate"), ("R", "rebuild")])
async def test_recreate_on_a_container_targets_only_its_service(tmp_path, monkeypatch, key, action):
    service = ProjectService()
    app, _docker = create_app(tmp_path, monkeypatch, service)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles) and ready(app))
        child = "profile-child:profile:Orders:orders-api"
        select_key(app, child)
        await until(pilot, lambda: app._selection_key == child)
        target = app.selected_container.compose_service
        assert target
        await pilot.press(key)
        assert app.query_one("#inline-compose").display
        plan = app._inline_plan
        assert (plan.action, plan.service) == (action, target)
        assert f"/ {target}?" in message(app)
        await pilot.click("#inline-compose-confirm")
        await until(pilot, service.began("orders").is_set)
        assert app._compose_tasks["orders"] is not None
        service.gate("orders").set()
        await until(pilot, lambda: app._compose_tasks["orders"].done())
        assert f"Starting {action}: orders / {target}" in buffered(app, "orders")


@pytest.mark.parametrize(("key", "action"), [("r", "recreate"), ("R", "rebuild")])
async def test_recreate_on_a_profile_row_still_targets_the_whole_profile(
    tmp_path, monkeypatch, key, action
):
    service = ProjectService()
    app, _docker = create_app(tmp_path, monkeypatch, service)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles) and ready(app))
        select_key(app, "profile:Orders")
        await until(pilot, lambda: app._selection_key == "profile:Orders")
        await pilot.press(key)
        plan = app._inline_plan
        assert (plan.action, plan.service) == (action, None)
