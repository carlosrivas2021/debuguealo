"""T in Code opens a shell at the root of the project shown in the file tree."""

import json
import sys

from test_code_project_store import configure
from test_terminal_view import FakeSession
from test_tui_grouping import Docker, until
from textual.widgets import DataTable

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.code_workspace import _display_path
from debugpilot.tui.terminal_view import TerminalPane


def shell_app(monkeypatch, tmp_path):
    made: list[FakeSession] = []

    def factory(*, on_output, on_exit=None):
        session = FakeSession(on_output=on_output, on_exit=on_exit)
        made.append(session)
        return session

    monkeypatch.setattr("debugpilot.tui.terminal_view.TerminalSession", factory)
    store = configure(monkeypatch, tmp_path)
    roots = [tmp_path / "orders", tmp_path / "catalog"]
    for root in roots:
        root.mkdir()
    store.path.write_text(json.dumps({"version": 1, "configurations": [
        {"name": root.name.capitalize(), "workspaceFolder": str(root),
         "command": [sys.executable, "-c", "pass"]}
        for root in roots
    ]}), encoding="utf-8")
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    return app, roots, made


def shells(app):
    return [pane for pane in app.query(".code-shell").results(TerminalPane)]


def shown_shell(app):
    visible = [pane for pane in shells(app) if pane.display]
    assert len(visible) <= 1
    return visible[0] if visible else None


async def choose(pilot, app, row):
    table = app.query_one("#code-projects", DataTable)
    table.focus()
    table.move_cursor(row=row)
    await pilot.pause()


async def test_t_opens_a_shell_at_the_project_root_and_keeps_it_per_project(
    monkeypatch, tmp_path
):
    app, (orders, catalog), made = shell_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.click("#area-code")
        await choose(pilot, app, 0)  # Orders, first in launch.json.
        await pilot.press("t")
        await until(pilot, lambda: len(made) == 1 and shown_shell(app) is not None)
        assert made[0].host_open[0] == orders
        shell = shown_shell(app)
        assert shell.active and app.focused is shell
        # The border's title names the folder the shell opened in.
        assert shell.border_title == f"Shell · {orders}"
        assert shell.styles.border_top[0] != ""
        assert not app.query_one("#code-terminal").display
        # A live shell types the letter instead of opening another one.
        await pilot.press("t")
        assert made[0].writes == ["t"] and len(made) == 1

        # Another project has its own shell; the first one keeps running.
        await choose(pilot, app, 1)  # Catalog.
        assert shown_shell(app) is None
        await pilot.press("t")
        await until(pilot, lambda: len(made) == 2 and shown_shell(app) is not None)
        assert made[1].host_open[0] == catalog
        await choose(pilot, app, 0)
        assert shown_shell(app) is shell and shell.active and not made[0].closed

        # T outside the shell goes back to the run output and keeps the shell alive.
        await pilot.press("t")
        assert shown_shell(app) is None and shell.active
        await pilot.press("t")
        assert shown_shell(app) is shell and len(made) == 2

        # `exit` hides the shell and gives the keys back to the profiles.
        shell.focus()
        await pilot.pause()
        made[0].exit()
        await until(pilot, lambda: not shell.active and shown_shell(app) is None)
        assert app.focused is app.query_one("#code-projects", DataTable)
        # The next T opens a new one in the same folder, in place.
        await pilot.press("t")
        await until(pilot, lambda: len(made) == 3 and shell.active)
        assert made[2].host_open[0] == orders and shown_shell(app) is shell
    assert all(session.closed for session in (made[1], made[2]))


async def test_t_needs_a_project_in_the_tree(monkeypatch, tmp_path):
    app, _roots, made = shell_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.click("#area-code")
        app.query_one("#code-filter").value = "zzz"  # No profile, so no project.
        await pilot.pause()
        app.query_one("#code-projects", DataTable).focus()
        await pilot.press("t")
        await pilot.pause()
        assert not made and not shells(app)


def test_a_folder_under_home_is_shown_from_the_tilde(monkeypatch, tmp_path):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert _display_path(tmp_path / "projects" / "shop") == "~/projects/shop"
    assert _display_path(tmp_path) == "~"
    assert _display_path(tmp_path.parent / "elsewhere") == str(tmp_path.parent / "elsewhere")


async def test_quitting_while_a_shell_is_opening_never_leaves_it_running(monkeypatch, tmp_path):
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()
    events: list[str] = []

    class SlowSession(FakeSession):
        async def open_host(self, cwd, rows, columns):
            events.append("opening")
            entered.set()
            try:
                await release.wait()  # Bash takes a while to start.
            except asyncio.CancelledError:
                events.append("open cancelled")
                raise
            events.append("opened")
            await super().open_host(cwd, rows, columns)

        async def close_session(self):
            events.append("closed")
            await super().close_session()

    app, _roots, _made = shell_app(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "debugpilot.tui.terminal_view.TerminalSession",
        lambda **callbacks: SlowSession(**callbacks),
    )
    async def quit_while_opening():
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.click("#area-code")
            await choose(pilot, app, 0)
            pressing = asyncio.create_task(pilot.press("t"))
            await asyncio.wait_for(entered.wait(), 10)
            # Code keeps handling keys while Bash starts.
            await asyncio.wait_for(pressing, 5)
            # Quit while Bash is still starting.

    # Quitting never waits for a startup that hangs.
    await asyncio.wait_for(quit_while_opening(), 15)
    release.set()
    await asyncio.sleep(0.2)  # Let a startup that was not cancelled finish.
    # Whatever the order, the session ends closed: never a Bash left running.
    assert "closed" in events
    assert events[-1] in {"closed", "open cancelled"}
    assert "opened" not in events or events.index("opened") < len(events) - 1
