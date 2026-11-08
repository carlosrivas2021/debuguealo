import asyncio

from test_tui_grouping import Docker, item, ready, request_logs, select_key, until
from textual.widgets import DataTable, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import LogEntry
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.container_list import container_rows
from debugpilot.tui.log_viewer import LogViewer


def test_grouped_labels_only_remove_the_exact_project_prefix():
    inventory = [
        item("shop-api-1", "shop", "api"),
        item("shop_worker_1", "shop", "worker"),
        item("custom-api", "shop", "api"),
        item("shopper-api-1", "shop", "api"),
        item("shop-standalone"),
    ]
    rows = {row.key: row for row in container_rows(inventory)}
    assert rows["container:shop-api-1"].label.strip() == "api-1"
    assert rows["container:shop_worker_1"].label.strip() == "worker_1"
    for name in ("custom-api", "shopper-api-1", "shop-standalone"):
        assert rows[f"container:{name}"].label.strip() == name
    assert rows["container:shop-api-1"].container.id == "shop-api-1"


async def test_project_merges_tagged_logs_and_closes_all_streams_when_switching():
    class LoggingDocker(Docker):
        async def stream_logs(self, name, **_options):
            self.opened.append(name)
            try:
                yield LogEntry(text="same message", stream="stderr")
                await asyncio.Event().wait()
            finally:
                self.closed.append(name)

    docker = LoggingDocker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "project:orders")
        await until(pilot, lambda: app.selected_project == "orders")
        await request_logs(pilot, app)
        viewer = app.query_one(LogViewer)
        await until(pilot, lambda: len(viewer.buffer.entries()) == 2)
        assert {entry.text for entry in viewer.buffer.entries()} == {
            "[api] same message",
            "[worker] same message",
        }
        assert all(entry.stream == "stderr" for entry in viewer.buffer.entries())
        assert set(docker.opened[-2:]) == {"orders-api", "orders-worker"}
        app.action_retry_logs()
        await until(pilot, lambda: docker.opened.count("orders-worker") == 2)
        select_key(app, "container:gateway-api")
        await until(
            pilot,
            lambda: (
                app.selected_container is not None and app.selected_container.id == "gateway-api"
            ),
        )
        await until(pilot, lambda: docker.closed.count("orders-worker") == 2)
        # The new selection closed logs; request them for the selected container.
        await request_logs(pilot, app)
        await until(pilot, lambda: len(viewer.buffer.entries()) == 1)
        assert viewer.buffer.entries()[0].text == "same message"
        assert viewer.query_one(DataTable).is_mounted
    assert sorted(docker.closed) == sorted(docker.opened)


async def test_group_failure_isolated_and_inventory_membership_refreshes_streams():
    class FailingDocker(Docker):
        async def stream_logs(self, name, **_options):
            self.opened.append(name)
            try:
                if name == "orders-api":
                    raise DockerError("Test stream failure")
                yield LogEntry(text="alive")
                await asyncio.Event().wait()
            finally:
                self.closed.append(name)

    docker = FailingDocker()
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "project:orders")
        await until(pilot, lambda: app.selected_project == "orders")
        await request_logs(pilot, app)
        viewer = app.query_one(LogViewer)
        await until(pilot, lambda: any(e.text == "[worker] alive" for e in viewer.buffer.entries()))
        await until(
            pilot,
            lambda: "Test stream failure" in str(app.query_one("#log-state", Static).render()),
        )
        assert "orders-worker" not in docker.closed
        docker.inventory.append(item("orders-extra-1", "orders", "extra"))
        await until(pilot, lambda: "orders-extra-1" in docker.opened)
        await until(pilot, lambda: len(viewer.buffer.entries()) == 2)
        assert {e.text for e in viewer.buffer.entries()} == {"[worker] alive", "[extra-1] alive"}
    assert sorted(docker.closed) == sorted(docker.opened)


async def test_large_group_does_not_open_unbounded_streams():
    docker = Docker()
    docker.inventory = [item(f"orders-api-{number}", "orders", "api") for number in range(33)]
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        await request_logs(pilot, app)
        await until(pilot, lambda: len(docker.opened) == 1)
        select_key(app, "project:orders")
        await until(pilot, lambda: app.selected_container is None)
        await request_logs(pilot, app)
        await until(pilot, lambda: "over 32" in str(app.query_one("#log-state", Static).render()))
        assert len(docker.opened) == 1
        assert docker.closed == docker.opened
