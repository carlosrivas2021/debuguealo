"""Container detail cards and the Compose project overview."""

from datetime import UTC, datetime

from test_tui_grouping import Docker, ready, select_key, until
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import ContainerInfo, PortMapping
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.container_details import ContainerDetails


def container(identity, project, service, state="running", status="Up 3 hours", ports=()):
    labels = {"com.docker.compose.project.working_dir": f"/srv/{project}"} if project else {}
    return ContainerInfo(
        id=identity,
        name=identity,
        image=f"{service or identity}:local",
        state=state,
        status=status,
        created_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        labels=labels,
        ports=ports,
        compose_project=project,
        compose_service=service,
    )


class Fleet(Docker):
    def __init__(self):
        super().__init__()
        web_port = PortMapping(private_port=80, public_port=8080, host_ip="127.0.0.1")
        self.inventory = [
            container("shop-web", "shop", "web", ports=(web_port,)),
            container("shop-db", "shop", "db", state="exited", status="Exited (0) 2 hours ago"),
        ]


def start(docker):
    return DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)


def test_inventory_keeps_docker_status_text():
    info = ContainerInfo.from_docker({"Id": "abc", "Status": "Up 3 hours"})
    assert info.status == "Up 3 hours"
    assert ContainerInfo.from_docker({"Id": "abc"}).status == ""


async def test_container_selection_shows_the_cards_with_the_record_values():
    docker = Fleet()
    app = start(docker)
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:shop-web")
        details = app.query_one(ContainerDetails)
        await until(pilot, lambda: details.display)
        cards = {card.border_title: str(card.render()) for card in details.cards()}
        assert list(cards) == ["Status", "Image", "Network", "Compose", "Runtime"]
        assert "running" in cards["Status"] and "Up 3 hours" in cards["Status"]
        assert "Created: 2026-01-02" in cards["Status"]
        assert "web:local" in cards["Image"] and "ID: shop-web" in cards["Image"]
        assert "127.0.0.1:8080->80/tcp" in cards["Network"]
        assert "shop" in cards["Compose"] and "web" in cards["Compose"]
        assert "/srv/shop" in cards["Compose"]
        assert docker.opened == []


async def test_project_selection_shows_overview_table_without_logs():
    docker = Fleet()
    app = start(docker)
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "project:shop")
        overview = app.query_one("#project-overview")
        await until(pilot, lambda: overview.display)
        assert not app.query_one("#logs-panel").display
        assert not app.query_one(ContainerDetails).display
        assert "shop · 1 / 2 running" in str(app.query_one("#project-overview-title").render())
        table = app.query_one("#project-overview-table", DataTable)
        rows = {table.get_row_at(index)[0]: table.get_row_at(index) for index in range(2)}
        assert set(rows) == {"web", "db"}
        assert "Up 3 hours" in rows["web"] and "127.0.0.1:8080->80/tcp" in rows["web"]
        assert "Exited (0) 2 hours ago" in rows["db"]
        assert "Ctrl+L" in str(app.query_one("#container-info").render())
        assert docker.opened == []
        await pilot.press("ctrl+l")
        # Combined logs follow active members only, as before.
        await until(pilot, lambda: docker.opened == ["shop-web"])
        assert not overview.display and app.query_one("#logs-panel").display


async def test_uptime_text_changes_do_not_restart_open_logs():
    docker = Fleet()
    app = start(docker)
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:shop-web")
        await pilot.press("ctrl+l")
        await until(pilot, lambda: docker.opened == ["shop-web"])
        for minutes in range(3):
            docker.inventory = [
                c.model_copy(update={"status": f"Up {minutes} minutes"})
                if c.name == "shop-web"
                else c
                for c in docker.inventory
            ]
            await pilot.pause(0.15)
        assert docker.opened == ["shop-web"] and docker.closed == []
