"""Central code profiles and one independently owned local execution."""

import asyncio

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.code_projects import CodeProjectStore
from debugpilot.tui.code_debug import CodeDebug
from debugpilot.tui.code_terminal import CodeTerminal
from debugpilot.tui.source_browser import SourceBrowser


class CodeWorkspace(Vertical):
    def __init__(self):
        super().__init__(id="code-workspace")
        self.store = CodeProjectStore()
        self._profiles = {}
        self._shutting_down = False
        self._run_button = Button("Run (F5)", id="code-run")
        self._debug_button = Button("Debug (Shift+F5)", id="code-debug-start")
        self._reconnect_button = Button("Reconnect", id="code-reconnect")
        self._reconnect_button.display = False
        self._browser = SourceBrowser()
        self._debug = CodeDebug(self._browser, self._state, self._debug_finished)
        self._stop_button = Button("Stop", id="code-stop", disabled=True)
        self._run_state = Static(
            "Ready. Select a profile and press F5.", id="code-run-state", markup=False
        )
        self._pane = CodeTerminal(
            self._run_context_state, id="code-terminal",
            escape_hook=lambda: self.query_one(DataTable).focus(),
        )

    def compose(self) -> ComposeResult:
        yield Static("PROJECTS", id="code-title")
        yield Static("", id="code-status", markup=False)
        with Horizontal(id="code-actions"):
            yield Button("Reload code profiles", id="code-reload")
            yield self._run_button
            yield self._debug_button
            yield self._reconnect_button
            yield self._stop_button
        yield DataTable(id="code-projects", cursor_type="row", zebra_stripes=True)
        yield self._browser
        yield self._run_state
        yield self._debug
        yield self._pane
        yield Static(
            "F5: run without debug · Escape: return to profiles · Stop: end owned Code process. "
            "Shift+F5: debug/attach · Continue: button · F10/F11/Shift+F11: step. "
            "One session per saved profile; distinct profiles may run/debug/attach together. "
            "Attach Disconnect leaves the target to Containers; Reconnect is explicit; "
            "the same attach endpoint cannot be attached twice. Debug output has no stdin. "
            "Source is read-only.",
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
            live = {
                context.profile.name: context.profile
                for context in [*self._pane.contexts.values(), *self._debug.contexts.values()]
                if (
                    getattr(context, 'pending', False) or context.active
                    or getattr(context, 'stopping', False)
                    or getattr(context, 'unexpected_disconnect', False)
                )
            }
            profiles = [live.pop(profile.name, profile) for profile in profiles]
            profiles.extend(live.values())
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
            live = {
                context.profile.name: context.profile
                for context in [*self._pane.contexts.values(), *self._debug.contexts.values()]
                if (
                    getattr(context, 'pending', False) or context.active
                    or getattr(context, 'stopping', False)
                    or getattr(context, 'unexpected_disconnect', False)
                )
            }
            self._profiles = live
            for profile in live.values():
                table.add_row(
                    profile.name, str(profile.root), repr(list(profile.command)), key=profile.name
                )
            message = str(error)
        self.query_one("#code-status", Static).update(message)
        self.select_source_project()

    @on(DataTable.RowHighlighted, "#code-projects")
    def select_source_project(self):
        table = self.query_one(DataTable)
        profile = None
        if table.row_count:
            profile = self._profiles.get(table.ordered_rows[table.cursor_row].key.value)
        self._debug.select_profile(profile)
        debug_context = self._debug.selected
        if debug_context is not None and (
            debug_context.active or debug_context.unexpected_disconnect
        ):
            self._pane.select_profile(None)
        else:
            self._pane.select_profile(profile)
        pinned = self._pane.selected_context
        debug_pinned = debug_context is not None and (
            debug_context.active or debug_context.stopping
            or debug_context.unexpected_disconnect
        )
        run_pinned = pinned is not None and (
            pinned.pending or pinned.active or pinned.stopping
        )
        source_profile = (
            debug_context.profile if debug_pinned
            else pinned.profile if run_pinned
            else profile
        )
        self.query_one(SourceBrowser).set_project(
            source_profile.root if source_profile is not None else None
        )
        run_context = self._pane.selected_context
        debug_context = self._debug.selected
        if run_context is not None:
            self._state(run_context.state)
        elif debug_context is not None:
            self._state(debug_context.state)
        elif profile is not None:
            self._state(f"Ready: {profile.name}")
        selected = debug_context
        self._reconnect_button.display = bool(
            selected is not None and selected.unexpected_disconnect
        )
        self._stop_button.label = (
            "Disconnect" if selected is not None and selected.profile.attach is not None
            and (selected.active or selected.unexpected_disconnect) else "Stop"
        )
        self._sync_controls()

    def _state(self, message):
        self._run_state.update(message)

    def _debug_finished(self, unexpected_disconnect=False):
        self._reconnect_button.display = bool(unexpected_disconnect)
        self._sync_controls()

    def _sync_controls(self):
        run_context = self._pane.selected_context
        debug_context = self._debug.selected
        run_selected = bool(run_context and (
            run_context.pending or run_context.active or run_context.stopping
        ))
        debug_selected = bool(debug_context and (
            debug_context.active or debug_context.stopping
            or debug_context.unexpected_disconnect
        ))
        self._run_button.disabled = self._shutting_down
        self._debug_button.disabled = self._shutting_down
        self._stop_button.disabled = not (run_selected or debug_selected)
        self._stop_button.label = (
            "Disconnect" if debug_selected and debug_context.profile.attach is not None
            else "Stop"
        )

    def _run_context_state(self, profile, message):
        if self._pane.selected_context is not None and (
            self._pane.selected_context.profile.name == profile.name
        ):
            self._state(message)
            self._sync_controls()

    @on(Button.Pressed, "#code-run")
    def run_selected(self):
        if self._shutting_down:
            return
        table = self.query_one(DataTable)
        if not table.row_count:
            self._state("No Code profile selected. Open code launch.json to add one.")
            return
        profile = self._profiles[table.ordered_rows[table.cursor_row].key.value]
        debug_context = self._debug.context_for(profile)
        if debug_context is not None and (
            debug_context.active or debug_context.stopping or debug_context.unexpected_disconnect
        ):
            self._debug.select_context(debug_context)
            self._pane.display = False
            self._state(debug_context.state)
            self._sync_controls()
            return
        run_context = self._pane.contexts.get(profile.name)
        if run_context is not None and (
            run_context.pending or run_context.active or run_context.stopping
        ):
            self._pane.select_profile(profile)
            self._debug.display = False
            self._state(run_context.state)
            self._pane.focus()
            self._sync_controls()
            return
        if not profile.command:
            message = (
                f"{profile.name} is attach-only. Use Shift+F5 to connect; "
                "F5 does not start a local process."
            )
            self._state(message)
            self.app.notify(message, severity="warning")
            return
        self._debug.display = False
        context, created = self._pane.prepare_profile(profile)
        self._pane.display = True
        if created:
            context.start_task = asyncio.create_task(self._start(profile))
            context.start_task.add_done_callback(
                lambda task, profile=profile: self._run_start_finished(profile, task)
            )
        self._sync_controls()

    @on(Button.Pressed, "#code-reconnect")
    def reconnect(self):
        if (
            self._shutting_down
            or self._debug.profile is None
            or self._debug.profile.attach is None
        ):
            return
        profile = self._debug.profile
        run_context = self._pane.contexts.get(profile.name)
        if run_context is not None and (
            run_context.pending or run_context.active or run_context.stopping
        ):
            return
        self._reconnect_button.display = False
        self._debug.start(profile)
        self._sync_controls()
        self._stop_button.label = "Disconnect"

    @on(Button.Pressed, "#code-debug-start")
    def debug_selected(self):
        self._reconnect_button.display = False
        if self._shutting_down:
            return
        table = self.query_one(DataTable)
        if not table.row_count:
            self._state("No Code profile selected. Open code launch.json to add one.")
            return
        profile = self._profiles[table.ordered_rows[table.cursor_row].key.value]
        run_context = self._pane.contexts.get(profile.name)
        if run_context is not None and (
            run_context.pending or run_context.active or run_context.stopping
        ):
            self._pane.select_profile(profile)
            self._pane.display = True
            self._debug.display = False
            self._state(run_context.state)
            self._pane.focus()
            self._sync_controls()
            return
        debug_context = self._debug.context_for(profile)
        if debug_context is not None and debug_context.active:
            self._debug.select_context(debug_context)
            self._pane.display = False
            self._state(debug_context.state)
            self._sync_controls()
            return
        self._pane.display = False
        self._debug.start(profile)
        self._sync_controls()

    @on(SourceBrowser.BreakpointsChanged)
    def breakpoints_changed(self, event):
        self._debug.breakpoints_changed(event)

    def debug_control(self, command):
        self._debug.resume(command)

    async def _start(self, profile):
        context = self._pane.contexts.get(profile.name)
        if context is not None:
            await self._pane.start_context(context)

    def _run_start_finished(self, profile, task):
        context = self._pane.contexts.get(profile.name)
        if (
            context is not None and context.start_task is task
            and context.pending and task.done()
        ):
            context.pending = False
            context.active = False
            context.state = "Stopped" if task.cancelled() else f"Ready: {profile.name}"
            if self._pane.selected_context is context:
                self._state(context.state)
                self._sync_controls()

    @on(Button.Pressed, "#code-stop")
    async def stop(self):
        run_context = self._pane.selected_context
        if run_context is not None and (
            run_context.pending or run_context.active or run_context.stopping
        ):
            await self._pane.close_context(run_context)
            if self._pane.selected_context is run_context:
                self._state(run_context.state)
                if run_context.active:
                    self.app.notify(run_context.state, severity="warning")
            self._sync_controls()
            return
        debug_context = self._debug.selected
        disconnecting = bool(
            debug_context and debug_context.profile.attach is not None
            and (debug_context.active or debug_context.stopping
                 or debug_context.unexpected_disconnect)
        )
        if debug_context is None or not (
            debug_context.active or debug_context.stopping
            or debug_context.unexpected_disconnect
        ):
            self._sync_controls()
            return
        warning = await self._debug.close_context(debug_context)
        if self._debug.selected is debug_context:
            if debug_context.close_error:
                message = f"Stop incomplete: {debug_context.close_error} Press Stop to retry."
                self._state(message)
                self.app.notify(message, severity="warning")
            elif disconnecting and warning:
                message = f"Disconnected; target state UNKNOWN: {warning}"
                self._state(message)
                self.app.notify(message, severity="warning")
            else:
                self._state(
                    "Disconnected; target remains managed by Containers"
                    if disconnecting else "Stopped"
                )
            self._reconnect_button.display = False
        self._sync_controls()

    async def shutdown(self):
        self._shutting_down = True
        await self._pane.close_all()
        await self._debug.close_all()

    async def on_unmount(self):
        await self.shutdown()
