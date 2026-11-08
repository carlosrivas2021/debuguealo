"""Selecting a container shows its details; logs stream only on request."""

import asyncio
from datetime import UTC, datetime

from test_tui_grouping import Docker, item, select_key, until

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.models import ContainerInfo, PortMapping
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.container_details import ContainerDetails


def start(docker):
    return DebugPilotApp(DebugPilotEngine(Settings(), docker=docker), refresh_interval=0.05)


def panels(app):
    return app.query_one(ContainerDetails).display, app.query_one("#logs-panel").display


async def test_selection_shows_details_without_opening_a_log_stream():
    docker = Docker()
    app = start(docker)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory)
        select_key(app, "container:catalog-api")
        await until(pilot, lambda: panels(app) == (True, False))
        await pilot.pause(0.3)
        assert docker.opened == []
        content = app.query_one(ContainerDetails).text()
        assert "Name: catalog-api" in str(content)


async def test_ctrl_l_opens_logs_and_a_new_selection_returns_to_details():
    docker = Docker()
    app = start(docker)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory)
        select_key(app, "container:catalog-api")
        await pilot.press("ctrl+l")
        await until(pilot, lambda: docker.opened == ["catalog-api"])
        assert panels(app) == (False, True)
        select_key(app, "container:catalog-worker")
        await until(pilot, lambda: docker.closed == ["catalog-api"])
        await until(pilot, lambda: panels(app) == (True, False))
        await pilot.pause(0.3)
        assert docker.opened == ["catalog-api"]


async def test_d_closes_open_logs_and_shows_details():
    docker = Docker()
    app = start(docker)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory)
        select_key(app, "container:catalog-api")
        await pilot.press("ctrl+l")
        await until(pilot, lambda: docker.opened == ["catalog-api"])
        await pilot.press("d")
        await until(pilot, lambda: docker.closed == ["catalog-api"])
        assert panels(app) == (True, False)


async def test_project_logs_open_only_on_request():
    docker = Docker()
    app = start(docker)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory)
        select_key(app, "project:orders")
        await pilot.pause(0.3)
        assert docker.opened == []
        await pilot.press("ctrl+l")
        await until(pilot, lambda: sorted(docker.opened) == ["orders-api", "orders-worker"])


async def test_open_logs_survive_refreshes_and_a_state_change_of_the_same_container():
    class Changing(Docker):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def list_containers(self):
            self.calls += 1
            return self.inventory

    docker = Changing()
    app = start(docker)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._inventory)
        select_key(app, "container:catalog-api")
        await pilot.press("ctrl+l")
        await until(pilot, lambda: docker.opened == ["catalog-api"])
        docker.inventory = [
            item("catalog-api", "catalog", "api", state="restarting")
            if c.id == "catalog-api"
            else c
            for c in docker.inventory
        ]
        calls = docker.calls
        await until(pilot, lambda: docker.calls >= calls + 3)
        assert panels(app) == (False, True)
        assert docker.opened[-1] == "catalog-api"


def test_inventory_port_order_is_deterministic():
    raw = {
        "Id": "abc",
        "Ports": [
            {"PrivatePort": 8080, "PublicPort": 18080, "Type": "tcp", "IP": "0.0.0.0"},
            {"PrivatePort": 2345, "PublicPort": 2345, "Type": "tcp", "IP": "0.0.0.0"},
            {"PrivatePort": 2345, "PublicPort": 2345, "Type": "tcp", "IP": "::"},
        ],
    }
    forward = ContainerInfo.from_docker(raw)
    backward = ContainerInfo.from_docker({**raw, "Ports": raw["Ports"][::-1]})
    assert forward == backward
    assert forward.ports[0] == PortMapping(
        private_port=2345, public_port=2345, protocol="tcp", host_ip="0.0.0.0"
    )


async def test_unchanged_selection_with_reordered_ports_keeps_one_log_stream():
    ports = [
        {"PrivatePort": 80, "PublicPort": 8080, "Type": "tcp", "IP": "0.0.0.0"},
        {"PrivatePort": 443, "PublicPort": 8443, "Type": "tcp", "IP": "0.0.0.0"},
    ]

    class Flipping(Docker):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def list_containers(self):
            self.calls += 1
            order = ports if self.calls % 2 else ports[::-1]
            web = ContainerInfo.from_docker(
                {
                    "Id": "web",
                    "Names": ["/web"],
                    "State": "running",
                    "Ports": order,
                    "Created": int(datetime(2026, 1, 1, tzinfo=UTC).timestamp()),
                }
            )
            return [*self.inventory, web]

    docker = Flipping()
    app = start(docker)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: "web" in app._inventory)
        select_key(app, "container:web")
        await pilot.press("ctrl+l")
        await until(pilot, lambda: docker.opened == ["web"])
        calls = docker.calls
        await until(pilot, lambda: docker.calls >= calls + 4)
        await asyncio.sleep(0)
        assert docker.opened == ["web"] and docker.closed == []
