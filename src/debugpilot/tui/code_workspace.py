"""Central code profiles and one independently owned local execution."""

import asyncio

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.code_projects import CodeProjectStore
from debugpilot.terminal.session import TerminalUnavailable
from debugpilot.tui.code_debug import CodeDebug
from debugpilot.tui.code_terminal import CodeTerminal
from debugpilot.tui.source_browser import SourceBrowser


class CodeWorkspace(Vertical):
    def __init__(self):
        super().__init__(id="code-workspace")
        self.store = CodeProjectStore()
        self._profiles = {}
        self._run_task = None
        self._stopping = False
        self._shutting_down = False
        self._run_button = Button("Run (F5)", id="code-run")
        self._debug_button = Button("Debug (Shift+F5)", id="code-debug-start")
        self._browser = SourceBrowser()
        self._debug = CodeDebug(self._browser, self._state, lambda: self._controls(False))
        self._stop_button = Button("Stop", id="code-stop", disabled=True)
        self._run_state = Static(
            "Ready. Select a profile and press F5.", id="code-run-state", markup=False
        )
        self._pane = CodeTerminal(
            self._finished, id="code-terminal",
            escape_hook=lambda: self.query_one(DataTable).focus(),
        )

    def compose(self) -> ComposeResult:
        yield Static("PROJECTS", id="code-title")
        yield Static("", id="code-status", markup=False)
        with Horizontal(id="code-actions"):
            yield Button("Reload code profiles", id="code-reload")
            yield self._run_button
            yield self._debug_button
            yield self._stop_button
        yield DataTable(id="code-projects", cursor_type="row", zebra_stripes=True)
        yield self._browser
        yield self._run_state
        yield self._debug
        yield self._pane
        yield Static(
            "F5: run without debug · Escape: return to profiles · Stop: end Code process tree. "
            "Shift+F5: Python debug · Continue: button · F10/F11/Shift+F11: step. "
            "Debug output has no stdin. Source is read-only.",
            id="code-capabilities",
        )

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Profile", "Project folder", "Command (argv)")
        self.reload_profiles()

    @on(Button.Pressed, "#code-reload")
    def reload_profiles(self) -> None:
        table = self.query_one(DataTable)
        selected = None
        if table.row_count:
            selected = table.ordered_rows[table.cursor_row].key.value
        table.clear()
        self._profiles = {}
        try:
            profiles = self.store.profiles()
            self._profiles = {profile.name: profile for profile in profiles}
            for profile in profiles:
                table.add_row(
                    profile.name, str(profile.root), repr(list(profile.command)), key=profile.name
                )
            keys = [profile.name for profile in profiles]
            if selected in keys:
                table.move_cursor(row=keys.index(selected))
            message = (
                f"{len(profiles)} code profile(s). {self.store.path}"
                if profiles
                else f"No code profiles. Open launch.json to register projects: {self.store.path}"
            )
        except ConfigurationError as error:
            message = str(error)
        self.query_one("#code-status", Static).update(message)
        self.select_source_project()

    @on(DataTable.RowHighlighted, "#code-projects")
    def select_source_project(self):
        table = self.query_one(DataTable)
        profile = None
        if table.row_count:
            profile = self._profiles.get(table.ordered_rows[table.cursor_row].key.value)
        self.query_one(SourceBrowser).set_project(profile.root if profile else None)

    def _state(self, message):
        self._run_state.update(message)

    def _controls(self, running):
        self._run_button.disabled = running
        self._debug_button.disabled = running
        self._stop_button.disabled = not running

    @on(Button.Pressed, "#code-run")
    def run_selected(self):
        pane = self.query_one(CodeTerminal)
        if self._shutting_down or self._stopping or self._debug.active or pane.active or (
            self._run_task is not None and not self._run_task.done()
        ):
            return
        table = self.query_one(DataTable)
        if not table.row_count:
            self._state("No Code profile selected. Open code launch.json to add one.")
            return
        profile = self._profiles[table.ordered_rows[table.cursor_row].key.value]
        self._debug.display = False
        self._pane.display = True
        self._state(f"Starting: {profile.name}")
        self._controls(True)
        self._run_task = asyncio.create_task(self._start(profile))

    @on(Button.Pressed, "#code-debug-start")
    def debug_selected(self):
        if self._shutting_down or self._stopping or self._debug.active or self._pane.active or (
            self._run_task is not None and not self._run_task.done()
        ):
            self.app.notify("A Code session is active. Stop it before starting another.")
            return
        table = self.query_one(DataTable)
        if not table.row_count:
            self._state("No Code profile selected. Open code launch.json to add one.")
            return
        profile = self._profiles[table.ordered_rows[table.cursor_row].key.value]
        self._pane.display = False
        self._controls(True)
        self._debug.start(profile)

    @on(SourceBrowser.BreakpointsChanged)
    def breakpoints_changed(self, event):
        self._debug.breakpoints_changed(event)

    def debug_control(self, command):
        self._debug.resume(command)

    async def _start(self, profile):
        try:
            await self.query_one(CodeTerminal).open_profile(profile)
            self._state(f"Running: {profile.name} · {profile.root}")
        except (TerminalUnavailable, OSError) as error:
            self._state(f"Unable to run {profile.name}: {error}")
            self._controls(False)

    def _finished(self, code, error):
        if not self._stopping and not self._shutting_down:
            self._state(error or f"Exited: {code}")
            self._controls(False)

    @on(Button.Pressed, "#code-stop")
    async def stop(self):
        self._stopping = True
        self._controls(True)
        try:
            task, self._run_task = self._run_task, None
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await self._debug.close()
            await self._pane.close_session()
            self._state("Stopped")
        finally:
            self._controls(False)
            self._stopping = False

    async def shutdown(self):
        self._shutting_down = True
        await self.stop()

    async def on_unmount(self):
        await self.shutdown()
