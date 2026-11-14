"""Live CPU and memory in the details card, polled only for the selected container."""

import asyncio

import pytest
from test_tui_detail_cards import Fleet, start
from test_tui_grouping import ready, select_key, until
from textual.widgets import Checkbox, DataTable

from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import ContainerStats
from debugpilot.tui.container_details import ContainerDetails

MIB, GIB = 1024 ** 2, 1024 ** 3


class StatsFleet(Fleet):
    def __init__(self, fail=False):
        super().__init__()
        self.samples = []
        self.fail = fail

    async def container_stats(self, container):
        self.samples.append(container)
        if self.fail:
            raise DockerError("Docker connection failed.", retryable=True)
        count = len(self.samples)
        # Each sample adds 200 CPU units over 1000 system units on 2 CPUs: 40%.
        return ContainerStats(cpu_total=200 * count, system_cpu=1000 * count, online_cpus=2,
                              memory_usage=48 * MIB, memory_limit=GIB)


def status(app):
    details = app.query_one(ContainerDetails)
    return next(str(card.render()) for card in details.cards() if card.border_title == "Status")


async def settle(pilot, cycles=6):
    # refresh_interval is 0.05 s in these tests; wait several polling periods.
    await pilot.pause(0.05 * cycles)


async def test_selected_running_container_shows_cpu_and_memory():
    docker = StatsFleet()
    app = start(docker)
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:shop-web")
        await until(pilot, lambda: "CPU: 40.0%" in status(app))
        assert "Memory: 48.0 MiB / 1.0 GiB (4.7%)" in status(app)
        assert set(docker.samples) == {"shop-web"}


async def test_cpu_waits_for_a_second_sample():
    docker = StatsFleet()
    app = start(docker)
    app.refresh_interval = 60  # Only the first sample arrives during this test.
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:shop-web")
        await until(pilot, lambda: "Memory: 48.0 MiB" in status(app))
        assert "CPU: —" in status(app)


async def test_polling_stops_for_stopped_containers_logs_and_projects():
    docker = StatsFleet()
    app = start(docker)
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:shop-web")
        await until(pilot, lambda: len(docker.samples) >= 2)
        # A stopped container has no stats to poll; stopped rows need "Show all".
        app.query_one("#show-all", Checkbox).value = True
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: any(row.key.value == "stopped:container:shop-db"
                                       for row in table.ordered_rows))
        select_key(app, "stopped:container:shop-db")
        await settle(pilot)
        count = len(docker.samples)
        await settle(pilot)
        assert len(docker.samples) == count
        assert "CPU: —" in status(app) and "Memory: —" in status(app)
        # Opening the logs hides the card, so polling stops too.
        select_key(app, "container:shop-web")
        await until(pilot, lambda: len(docker.samples) > count)
        await pilot.press("ctrl+l")
        await settle(pilot)
        count = len(docker.samples)
        await settle(pilot)
        assert len(docker.samples) == count
        # A project row shows the overview, not a container card.
        select_key(app, "project:shop")
        await settle(pilot)
        assert len(docker.samples) == count
    after_exit = len(docker.samples)
    await asyncio.sleep(0.3)
    assert len(docker.samples) == after_exit


@pytest.mark.parametrize("docker_type", [Fleet, lambda: StatsFleet(fail=True)],
                         ids=["no-stats-support", "docker-error"])
async def test_missing_stats_support_and_docker_errors_show_dashes(docker_type):
    app = start(docker_type())
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:shop-web")
        await settle(pilot)
        assert "CPU: —" in status(app) and "Memory: —" in status(app)
        assert "running" in status(app)


class RuntimeFleet(StatsFleet):
    def __init__(self):
        super().__init__()
        self.inspected = []

    async def container_runtime(self, container):
        from debugpilot.core.models import ContainerRuntime, MountInfo

        self.inspected.append(container)
        if container == "shop-db":
            return ContainerRuntime(exit_code=137, oom_killed=True, restart_policy="no")
        return ContainerRuntime(
            health="unhealthy", health_output="curl: (7) Failed to connect",
            restart_policy="unless-stopped", restart_count=2,
            mounts=(MountInfo(type="bind", source="/home/me/app", destination="/app"),
                    MountInfo(type="volume", source="pgdata", destination="/data",
                              read_only=True)),
            env_names=("PATH", "DATABASE_PASSWORD"),
        )


def runtime_card(app):
    details = app.query_one(ContainerDetails)
    return next(str(card.render()) for card in details.cards() if card.border_title == "Runtime")


async def test_runtime_card_shows_health_restarts_mounts_and_env_names():
    docker = RuntimeFleet()
    app = start(docker)
    async with app.run_test(size=(160, 50)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:shop-web")
        await until(pilot, lambda: "unhealthy" in runtime_card(app))
        card = runtime_card(app)
        assert "Health: unhealthy · curl: (7) Failed to connect" in card
        assert "Restart: unless-stopped · 2 restarts" in card
        assert "bind /home/me/app → /app" in card
        assert "volume pgdata → /data (read-only)" in card
        assert "Env: 2 variables, values hidden · PATH, DATABASE_PASSWORD" in card
        assert "Exit code" not in card
        app.query_one("#show-all", Checkbox).value = True
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: any(row.key.value == "stopped:container:shop-db"
                                       for row in table.ordered_rows))
        select_key(app, "stopped:container:shop-db")
        # A stopped container is inspected too: its exit code explains why it stopped.
        await until(pilot, lambda: "Exit code: 137 (OOM killed)" in runtime_card(app))
        card = runtime_card(app)
        assert "Health: —" in card and "Restart: no" in card
        assert "Mounts: None" in card and "Env: None" in card
        assert "shop-db" in docker.inspected and "shop-db" not in docker.samples


async def test_runtime_card_shows_dashes_without_inspect_support():
    docker = Fleet()
    app = start(docker)
    async with app.run_test(size=(160, 50)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:shop-web")
        await settle(pilot)
        card = runtime_card(app)
        assert "Health: —" in card and "Restart: —" in card
