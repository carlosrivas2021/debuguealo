import asyncio
import json

import pytest
from test_tui_grouping import Docker, item, until
from textual.events import Key
from textual.widgets import Button, Checkbox, DataTable, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.terminal_view import TerminalPane


class FakeSession:
    def __init__(self, *, on_output, on_exit=None):
        self.on_output = on_output
        self.on_exit = on_exit
        self.writes = []
        self.closed = False

    async def open_host(self, cwd, rows, columns):
        self.host = (cwd, rows, columns)

    async def open_container(self, container, endpoint, cwd, rows, columns):
        self.container = (container, endpoint, cwd, rows, columns)

    def write(self, value):
        self.writes.append(value)

    def resize(self, rows, columns):
        pass

    async def close_session(self):
        self.closed = True


@pytest.fixture
def fake_terminal(monkeypatch):
    made = []

    def factory(**callbacks):
        session = FakeSession(**callbacks)
        made.append(session)
        return session

    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", factory)
    return made


async def select_row(app, pilot, selector, key, expected_container_id):
    table = app.query_one(selector, DataTable)
    table.focus()
    table.move_cursor(
        row=next(index for index, row in enumerate(table.ordered_rows) if row.key.value == key)
    )
    await until(
        pilot,
        lambda: (
            app.selected_container is None and app.selected_project is not None
            if expected_container_id is None
            else app.selected_container is not None
            and app.selected_container.id == expected_container_id
        ),
    )


def app_for(docker, workspace):
    return DebugPilotApp(
        DebugPilotEngine(Settings(docker_endpoint="unix:///tmp/docker.sock"), docker=docker),
        refresh_interval=0.05,
        workspace=workspace,
    )


async def test_persistent_terminal_mount_does_not_start_a_session(fake_terminal, tmp_path):
    docker = Docker()
    app = app_for(docker, tmp_path)
    async with app.run_test(size=(120, 40)):
        panes = [
            app.query_one("#terminal-pane", TerminalPane),
            app.query_one("#container-terminal-pane", TerminalPane),
        ]
        assert all(pane.is_mounted and not pane.active for pane in panes)
        assert fake_terminal == []
        assert app.query_one("#terminal-context", Static)


async def test_c_opens_pinned_running_child_only_when_left_table_focused(fake_terminal, tmp_path):
    actual = item("a" * 64, "owned-project", "worker")
    sibling = item("b" * 64, "owned-project", "api")
    profile_path = tmp_path / ".debugpilot" / "launch.json"
    profile_path.parent.mkdir()
    profile_path.write_text(
        json.dumps({"version": 1, "configurations": [{
            "name": "Owned", "type": "docker-compose", "projectName": "owned-project"
        }]}),
        encoding="utf-8",
    )
    docker = Docker()
    docker.inventory = [actual, sibling]
    app = app_for(docker, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: table.row_count >= 3)
        child_key = next(
            row.key.value
            for row in table.ordered_rows
            if row.key.value.startswith("profile-child:") and row.key.value.endswith(actual.id)
        )
        await select_row(app, pilot, "#launch-profiles", child_key, actual.id)
        await pilot.press("c")
        await until(pilot, lambda: len(fake_terminal) == 1)
        session = fake_terminal[0]
        assert session.container[0].id == actual.id
        assert session.container[1] == "unix:///tmp/docker.sock"
        assert session.container[2] == tmp_path.resolve()
        pane = app.query_one("#container-terminal-pane", TerminalPane)
        assert pane.context.container.id == actual.id
        app.query_one("#log-state").focus()
        await pilot.press("c")
        assert len(fake_terminal) == 1
    assert fake_terminal[0].closed


async def test_h_is_independent_of_selection_and_uses_canonical_workspace(fake_terminal, tmp_path):
    docker = Docker()
    app = app_for(docker, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app.query_one("#launch-profiles", DataTable).row_count > 0)
        await select_row(app, pilot, "#launch-profiles", "project:catalog", None)
        assert app.selected_container is None
        await pilot.press("h")
        await until(pilot, lambda: len(fake_terminal) == 1)
        assert fake_terminal[0].host[0] == tmp_path.resolve()
        assert app.query_one("#terminal-pane", TerminalPane).context.kind == "host"
        assert app.query_one("#terminal-pane", TerminalPane).context.container is None
    assert fake_terminal[0].closed


async def test_terminal_owns_keys_escape_and_does_not_reopen_on_selection(fake_terminal, tmp_path):
    docker = Docker()
    docker.inventory = [item("demo-api", "demo", "api"), item("other-api", "other", "api")]
    app = app_for(docker, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app.query_one("#launch-profiles", DataTable).row_count > 0)
        table = app.query_one("#launch-profiles", DataTable)
        await select_row(app, pilot, "#launch-profiles", "container:demo-api", "demo-api")
        await pilot.press("c")
        await until(pilot, lambda: len(fake_terminal) == 1)
        pane = app.query_one("#container-terminal-pane", TerminalPane)
        context = pane.context
        await pilot.press("c", "h", "q", "d", "s", "r", "o", "ctrl+c")
        for character in "CHQDSRO":
            pane.post_message(Key(character, character))
        await pilot.pause()
        assert fake_terminal[0].writes == [
            "c", "h", "q", "d", "s", "r", "o", "\x03", "C", "H", "Q", "D", "S", "R", "O"
        ]
        await pilot.press("escape")
        assert app.focused is table
        await select_row(app, pilot, "#launch-profiles", "container:other-api", "other-api")
        await pilot.pause()
        assert pane.active and pane.context == context
        assert len(fake_terminal) == 1
    assert fake_terminal[0].closed


def footer_keys(app):
    return {
        key: active.binding.description
        for key, active in app.screen.active_bindings.items()
        if active.binding.show
    }


async def test_footer_shows_the_way_back_while_a_live_shell_owns_the_keys(fake_terminal, tmp_path):
    docker = Docker()
    docker.inventory = [item("demo-api", "demo", "api")]
    app = app_for(docker, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app.query_one("#launch-profiles", DataTable).row_count > 0)
        await select_row(app, pilot, "#launch-profiles", "container:demo-api", "demo-api")
        assert "q" in footer_keys(app)
        await pilot.press("c")
        await until(pilot, lambda: len(fake_terminal) == 1)
        await pilot.pause()
        # App shortcuts stay hidden so their keys reach the shell; Esc is advertised.
        assert footer_keys(app) == {"escape": "Back to list"}
        await pilot.press("escape")
        await pilot.pause()
        assert "q" in footer_keys(app) and "escape" not in footer_keys(app)
        assert fake_terminal[0].writes == []


async def test_o_minimizes_and_restores_the_host_terminal_without_closing_it(
    fake_terminal, tmp_path
):
    docker = Docker()
    app = app_for(docker, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.query_one("#launch-profiles", DataTable)
        await until(pilot, lambda: table.row_count > 0)
        table.focus()
        await pilot.pause()
        assert footer_keys(app).get("o") == "Host terminal"
        # With no host shell yet, O opens one, like H.
        await pilot.press("o")
        await until(pilot, lambda: len(fake_terminal) == 1)
        await pilot.pause()
        host = app.query_one("#host-terminal")
        pane = app.query_one("#terminal-pane", TerminalPane)
        await pilot.press("escape")
        assert footer_keys(app).get("o") == "Host terminal"
        await pilot.press("o")
        await pilot.pause()
        assert host.display and host.has_class("minimized") and not pane.display
        assert host.region.height <= 2 and pane.active and not fake_terminal[0].closed
        assert app.focused is table
        await pilot.press("o")
        await pilot.pause()
        assert not host.has_class("minimized") and pane.display and app.focused is pane
        assert fake_terminal[0].writes == []


async def test_host_without_workspace_fails_actionably_and_mount_stays_inactive(
    fake_terminal, tmp_path
):
    app = app_for(Docker(), None)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app.query_one("#launch-profiles", DataTable).row_count > 0)
        app.query_one("#launch-profiles", DataTable).focus()
        await pilot.press("h")
        assert fake_terminal == []
        status = str(app.query_one("#terminal-context", Static).render())
        assert "workspace" in status.lower()


async def test_container_shell_rejects_stopped_target_without_starting(fake_terminal, tmp_path):
    stopped = item("c" * 64, "demo", "api", state="exited")
    docker = Docker()
    docker.inventory = [stopped]
    app = app_for(docker, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#show-all", Checkbox).value = True
        await until(pilot, lambda: app.query_one("#launch-profiles", DataTable).row_count > 0)
        await select_row(
            app, pilot, "#launch-profiles", "stopped:container:" + stopped.id, stopped.id
        )
        await pilot.press("c")
        assert fake_terminal == []
        status = str(app.query_one("#terminal-context", Static).render())
        assert "running" in status.lower()


async def test_host_startup_error_is_visible_and_fake_session_is_closed(
    fake_terminal, monkeypatch, tmp_path
):
    async def fail_open(self, cwd, rows, columns):
        raise RuntimeError("Bash is unavailable")

    monkeypatch.setattr(FakeSession, "open_host", fail_open)
    app = app_for(Docker(), tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app.query_one("#launch-profiles", DataTable).row_count > 0)
        app.query_one("#launch-profiles", DataTable).focus()
        await pilot.press("h")
        await until(
            pilot,
            lambda: "Bash is unavailable"
            in str(app.query_one("#terminal-context", Static).render()),
        )
        assert not app.query_one("#terminal-pane", TerminalPane).active
    assert len(fake_terminal) == 1 and fake_terminal[0].closed


async def test_close_button_can_cancel_pending_host_open(monkeypatch, tmp_path):
    entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cancelled = asyncio.Event()

    class PendingSession(FakeSession):
        async def open_host(self, cwd, rows, columns):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def close_session(self):
            await super().close_session()
            closed.set()

    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", PendingSession)
    app = app_for(Docker(), tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app.query_one("#launch-profiles", DataTable).row_count > 0)
        app.query_one("#launch-profiles", DataTable).focus()
        opening = asyncio.create_task(pilot.press("h"))
        responsive = False
        startup_cancelled = False
        try:
            await asyncio.wait_for(entered.wait(), 2)
            app.query_one("#terminal-close", Button).press()
            try:
                await asyncio.wait_for(closed.wait(), 0.5)
                responsive = True
                startup_cancelled = cancelled.is_set()
            except TimeoutError:
                pass
        finally:
            release.set()
            await asyncio.wait_for(opening, 2)
        await pilot.pause()
        assert responsive, "Close terminal was blocked by pending H startup"
        assert startup_cancelled, "Close must cancel the pending startup owner"
        assert not app.query_one("#terminal-pane", TerminalPane).active
        assert "Terminal closed" in str(app.query_one("#terminal-context", Static).render())
