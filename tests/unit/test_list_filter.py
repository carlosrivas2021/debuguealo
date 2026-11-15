"""/ filters the Containers and Code lists, like k9s."""

import pytest
from launch_ui_helpers import save_remembered_profile
from test_code_debug_ui import debug_app
from test_tui_compose import Service
from test_tui_grouping import Docker, item, ready, select_key, until
from textual.widgets import DataTable, Input

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.docker.compose import ComposeProject
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.container_list import ContainerRow, filter_rows

WORKERS = [
    "project:catalog", "container:catalog-worker",
    "project:gateway", "container:gateway-worker",
    "project:orders", "container:orders-worker",
]


def keys(app, table="#launch-profiles"):
    return [row.key.value for row in app.query_one(table, DataTable).ordered_rows]


def test_a_matching_project_keeps_all_its_containers_and_a_match_keeps_its_project():
    rows = [
        ContainerRow("project:shop", "▾ shop", "2/2", project="shop"),
        ContainerRow("container:shop-api", "  shop-api", "running", container=item("shop-api")),
        ContainerRow("container:shop-db", "  shop-db", "running", container=item("shop-db")),
        ContainerRow("project:blog", "▾ blog", "1/1", project="blog"),
        ContainerRow("container:blog-api", "  blog-api", "running", container=item("blog-api")),
    ]
    assert [row.key for row in filter_rows(rows, "SHOP")] == [
        "project:shop", "container:shop-api", "container:shop-db"]
    assert [row.key for row in filter_rows(rows, "api")] == [
        "project:shop", "container:shop-api", "project:blog", "container:blog-api"]
    assert filter_rows(rows, "") == rows
    assert filter_rows(rows, "nothing") == []


async def test_slash_filters_the_containers_list_until_esc_clears_it():
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        everything = keys(app)
        assert len(everything) == 11
        table = app.query_one("#launch-profiles", DataTable)
        table.focus()
        field = app.query_one("#containers-filter", Input)
        assert not field.display
        await pilot.press("slash")
        await until(pilot, lambda: field.display and field.has_focus)
        await pilot.press(*"worker")
        await until(pilot, lambda: keys(app) == WORKERS)
        await pilot.press("enter")  # Enter keeps the filter and goes back to the list.
        await until(pilot, lambda: table.has_focus)
        assert field.display and field.value == "worker"
        await pilot.pause(0.3)  # Inventory refreshes keep the filter.
        assert keys(app) == WORKERS
        await pilot.press("slash")
        await until(pilot, lambda: field.has_focus)
        await pilot.press("escape")  # Esc clears it and shows everything again.
        await until(pilot, lambda: not field.display and keys(app) == everything)
        assert table.has_focus


async def test_slash_filters_code_profiles(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click("#area-code")
        await until(pilot, lambda: keys(app, "#code-projects") == ["one", "two"])
        app.query_one("#code-projects").focus()
        field = app.query_one("#code-filter", Input)
        await pilot.press("slash")
        await until(pilot, lambda: field.display and field.has_focus)
        await pilot.press("t", "w")
        await until(pilot, lambda: keys(app, "#code-projects") == ["two"])
        assert str(app.query_one("#code-count").render()) == "1/2"
        await pilot.press("enter")
        await until(pilot, lambda: app.query_one("#code-projects").has_focus)
        assert "two" in str(app.query_one("#code-run-state").render())  # It is selected.
        await pilot.press("slash", "escape")
        await until(pilot, lambda: keys(app, "#code-projects") == ["one", "two"])


@pytest.mark.parametrize("target", ["profile:Orders", "profile-child"])
async def test_filtering_out_the_selected_launch_profile_row_never_crashes(
        tmp_path, monkeypatch, target):
    (tmp_path / "compose.yaml").write_text("services: {}")
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _settings: Service())
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), refresh_interval=0.05)
    app._remember_compose_project(ComposeProject.create(tmp_path, ("compose.yaml",), "orders"))
    save_remembered_profile(app, "orders")
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        key = next(k for k in keys(app) if k.startswith(target))
        select_key(app, key)
        await pilot.pause()
        await pilot.press("slash", *"catalog")
        await until(pilot, lambda: keys(app) == [
            "project:catalog", "container:catalog-api", "container:catalog-worker"])
        await pilot.pause(0.3)  # Refreshes with the selected row hidden.
        await pilot.press("escape")
        await until(pilot, lambda: key in keys(app))


async def test_esc_in_the_list_clears_a_kept_filter():
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        everything = keys(app)
        table = app.query_one("#launch-profiles", DataTable)
        table.focus()
        await pilot.press("slash", *"worker", "enter")
        await until(pilot, lambda: table.has_focus and keys(app) == WORKERS)
        await pilot.press("escape")
        await until(pilot, lambda: keys(app) == everything)
        assert not app.query_one("#containers-filter").display and table.has_focus


async def test_esc_in_the_profile_list_clears_a_kept_filter(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.click("#area-code")
        profiles = app.query_one("#code-projects", DataTable)
        await until(pilot, lambda: keys(app, "#code-projects") == ["one", "two"])
        profiles.focus()
        await pilot.press("slash", "t", "w", "enter")
        await until(pilot, lambda: profiles.has_focus and keys(app, "#code-projects") == ["two"])
        await pilot.press("escape")
        await until(pilot, lambda: keys(app, "#code-projects") == ["one", "two"])
        assert not app.query_one("#code-filter").display
