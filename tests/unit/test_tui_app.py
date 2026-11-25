import asyncio
from datetime import UTC, datetime

from textual.widgets import DataTable, Input, Static
from typer.testing import CliRunner

from debugpilot import __version__, cli
from debugpilot.core.engine import DebugPilotEngine, EngineState
from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import ContainerInfo, LogEntry
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.log_viewer import LogViewer


def container(identity, state="running"):
    return ContainerInfo(
        id=identity,
        name=identity,
        image="demo:local",
        state=state,
        created_at=datetime.now(UTC),
        compose_project="demo",
        compose_service=identity,
    )


async def wait_until(pilot, condition):
    # Await observable state rather than racing the inventory timer under load. It returns
    # as soon as the condition holds; the generous deadline only bounds a real failure.
    async with asyncio.timeout(15):
        while not condition():
            await pilot.pause(0.02)


class Docker:
    def __init__(self):
        self.inventory = [container("api"), container("worker")]
        self.queues = {name: asyncio.Queue() for name in ("api", "worker")}
        self.opened = []
        self.closed = []
        self.failure = False
        self.cleanup_gate = None

    async def list_containers(self):
        if self.failure:
            raise DockerError("Docker is unavailable.")
        return self.inventory

    async def stream_logs(self, name, **_options):
        self.opened.append(name)
        try:
            while True:
                value = await self.queues[name].get()
                if isinstance(value, Exception):
                    raise value
                yield value
        finally:
            if self.cleanup_gate:
                await self.cleanup_gate.wait()
            await asyncio.sleep(0.01)
            self.closed.append(name)


async def test_dashboard_keyboard_switching_closes_old_stream_and_exit():
    docker = Docker()
    engine = DebugPilotEngine(Settings(), docker=docker)
    app = DebugPilotApp(engine, refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_until(pilot, lambda: getattr(app.selected_container, "id", None) == "api")
        # Logs stream only on request.
        await pilot.press("ctrl+l")
        await wait_until(pilot, lambda: docker.opened == ["api"])
        assert docker.opened == ["api"]
        docker.queues["api"].put_nowait(LogEntry(text="api entry"))
        await wait_until(pilot, lambda: bool(app.query_one(LogViewer).buffer.entries()))
        assert app.query_one(LogViewer).buffer.entries()[0].text == "api entry"
        app.query_one("#launch-profiles", DataTable).focus()
        await pilot.press("down")
        # A new selection closes the open logs; they open again only on request.
        await wait_until(pilot, lambda: docker.closed == ["api"])
        assert getattr(app.selected_container, "id", None) == "worker"
        assert docker.opened == ["api"]
        await pilot.press("ctrl+l")
        await wait_until(pilot, lambda: docker.opened == ["api", "worker"])
        assert docker.closed == ["api"] and docker.opened == ["api", "worker"]
        assert not app.query_one(LogViewer).buffer.entries()
        await pilot.press("ctrl+l")
        assert app.focused.id == "log-entries"
        app.query_one("#filter-logs", Input).focus()
        await pilot.press("q")
        assert app.query_one("#filter-logs", Input).value == "q"
        assert engine.state == EngineState.RUNNING
        await pilot.press("escape")
        app.query_one("#launch-profiles", DataTable).focus()
        await pilot.press("q")
    assert engine.state == EngineState.CLOSED
    assert docker.closed == ["api", "worker"]
    assert not engine._tasks


async def test_empty_disconnect_recovery_removal_and_log_errors():
    docker = Docker()
    docker.failure = True
    engine = DebugPilotEngine(Settings(), docker=docker)
    app = DebugPilotApp(engine, refresh_interval=0.05)
    async with app.run_test(size=(80, 24)) as pilot:
        await wait_until(
            pilot,
            lambda: "unavailable" in str(app.query_one("#docker-state", Static).render()).lower(),
        )
        assert "unavailable" in str(app.query_one("#docker-state", Static).render()).lower()
        docker.failure = False
        docker.inventory = []
        await wait_until(
            pilot,
            lambda: "connected" in str(app.query_one("#docker-state", Static).render()).lower(),
        )
        assert app.query_one("#launch-profiles", DataTable).row_count == 0
        docker.inventory = [container("api")]
        await wait_until(pilot, lambda: getattr(app.selected_container, "id", None) == "api")
        app.action_focus_logs()
        await wait_until(pilot, lambda: docker.opened == ["api"])
        assert docker.opened == ["api"]
        docker.queues["api"].put_nowait(DockerError("Unsupported logging driver."))
        await wait_until(
            pilot,
            lambda: (
                "Unsupported logging driver" in str(app.query_one("#log-state", Static).render())
            ),
        )
        assert "Unsupported logging driver" in str(app.query_one("#log-state", Static).render())
        docker.inventory = []
        await wait_until(
            pilot,
            lambda: (
                app.selected_container is None and not app.query_one(LogViewer).buffer.entries()
            ),
        )
        assert app.selected_container is None
        assert not app.query_one(LogViewer).buffer.entries()
        assert app.query_one("#log-entries").region.height > 0
    assert engine.state == EngineState.CLOSED


def test_cli_default_and_explicit_tui_dispatch_without_changing_existing_commands(monkeypatch):
    launches = []
    monkeypatch.setattr(cli, "_launch_tui", lambda config=None: launches.append(config))
    runner = CliRunner()
    assert runner.invoke(cli.app, []).exit_code == 0
    assert runner.invoke(cli.app, ["tui"]).exit_code == 0
    assert launches == [None, None]
    assert runner.invoke(cli.app, ["version"]).output.strip() == f"debugealo {__version__}"
    assert runner.invoke(cli.app, ["--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["logs", "api", "--tail", "-1"]).exit_code == 2
    assert len(launches) == 2


async def test_rapid_selection_during_cleanup_opens_only_latest_stream_once():
    docker = Docker()
    engine = DebugPilotEngine(Settings(), docker=docker)
    app = DebugPilotApp(engine, refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_until(pilot, lambda: getattr(app.selected_container, "id", None) == "api")
        app.action_focus_logs()
        await wait_until(pilot, lambda: docker.opened == ["api"])
        docker.cleanup_gate = asyncio.Event()
        table = app.query_one("#launch-profiles", DataTable)
        table.focus()
        await pilot.press("down")
        await pilot.press("up")
        await pilot.pause()
        await pilot.press("down")
        # Each selection closes logs; request them for the latest one before cleanup ends.
        app.action_focus_logs()
        docker.cleanup_gate.set()
        # Wait for the stream to open instead of a fixed delay, which a loaded machine
        # can outlast; then settle and check it opened only once, for the latest row.
        await wait_until(pilot, lambda: len(docker.opened) >= 2)
        await pilot.pause(0.2)
        assert docker.opened == ["api", "worker"]
        assert docker.closed == ["api"]
    assert docker.closed == ["api", "worker"]
    assert all(task.done() for task in app._ui_tasks)


async def test_compose_modal_does_not_stop_background_inventory_or_leak_on_exit():
    from debugpilot.tui.compose_dialog import ComposeDialog

    docker = Docker()
    engine = DebugPilotEngine(Settings(), docker=docker)
    app = DebugPilotApp(engine, refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        app._open_compose()
        await pilot.pause()
        await pilot.pause(0.15)
        assert isinstance(app.screen, ComposeDialog)
        assert all(not task.done() for task in app._ui_tasks)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ComposeDialog)
    assert engine.state == EngineState.CLOSED


async def test_one_failed_inventory_read_keeps_the_last_containers_shown():
    docker = Docker()
    engine = DebugPilotEngine(Settings(), docker=docker)
    app = DebugPilotApp(engine, refresh_interval=0.05)
    async with app.run_test(size=(80, 24)) as pilot:
        await wait_until(pilot, lambda: set(app._inventory) == {"api", "worker"})
        reads = []
        hold = asyncio.Event()

        async def flaky():
            reads.append(None)
            if len(reads) == 1:
                raise DockerError("Docker is busy.")
            await hold.wait()  # Freeze the next poll so the failed one is observable.
            return docker.inventory

        docker.list_containers = flaky
        await wait_until(pilot, lambda: len(reads) >= 2)
        # A single failed poll (a build loading Docker, a container removed mid-read)
        # is shown in the status line but never empties the inventory.
        assert "busy" in str(app.query_one("#docker-state", Static).render()).lower()
        assert set(app._inventory) == {"api", "worker"}
        assert app.query_one("#launch-profiles", DataTable).row_count > 0
        hold.set()


async def test_repeated_inventory_failures_still_empty_the_inventory():
    docker = Docker()
    engine = DebugPilotEngine(Settings(), docker=docker)
    app = DebugPilotApp(engine, refresh_interval=0.05)
    async with app.run_test(size=(80, 24)) as pilot:
        await wait_until(pilot, lambda: set(app._inventory) == {"api", "worker"})
        docker.failure = True
        await wait_until(pilot, lambda: not app._inventory)
        assert "unavailable" in str(app.query_one("#docker-state", Static).render()).lower()
