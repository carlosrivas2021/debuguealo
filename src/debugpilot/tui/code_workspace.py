"""Central code profiles and one independently owned local execution."""

import asyncio

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Static

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.code_projects import CodeProjectStore
from debugpilot.storage.git_head import current_branch
from debugpilot.tui.code_debug import CodeDebug
from debugpilot.tui.code_terminal import CodeTerminal
from debugpilot.tui.pane_splitter import PaneSplitter
from debugpilot.tui.source_browser import SourceBrowser
from debugpilot.tui.terminal_view import TerminalPane

# Left to right on screen; Ctrl+Left/Right move between them.
PANES = ("#code-projects", "#source-tree", "#source-text")
# The profile list keeps room for six profiles until resized; the file tree keeps four rows.
DEFAULT_PROFILE_ROWS = 6
MIN_PROFILE_ROWS = 2
MIN_TREE_ROWS = 4


class CodeWorkspace(Vertical):
    # Shown in the footer only while focus is inside Code; the app-level F9 stays hidden.
    BINDINGS = [
        Binding("f9", "app.toggle_breakpoint", "Breakpoint"),
        Binding("shift+f9", "app.edit_breakpoint", "Condition"),
        # Same key as the host terminal in Containers; text fields still type an "o".
        Binding("o", "app.toggle_code_terminal", "Output"),
        # Same key as stopping a container in Containers.
        Binding("s", "stop_run", "Stop"),
        # Move the boundary between profiles and files, like dragging the splitter.
        Binding("alt+up", "resize_profiles(-1)", show=False),
        Binding("alt+down", "resize_profiles(1)", show=False),
        # Priority: the read-only source would otherwise use them for word jumps.
        Binding("ctrl+left", "focus_pane(-1)", "Pane ←", priority=True),
        Binding("ctrl+right", "focus_pane(1)", "Pane →", priority=True),
    ]

    def __init__(self):
        super().__init__(id="code-workspace")
        self.store = CodeProjectStore()
        self._profiles = {}
        self._shutting_down = False
        self._profile_rows = DEFAULT_PROFILE_ROWS
        # Last view the user chose per profile ("run" or "debug"), used when neither is live.
        self._last_view: dict[str, str] = {}
        # Branch each profile was launched from; a live session keeps showing it after a checkout.
        self._launch_branches: dict[str, str | None] = {}
        self._run_button = Button("▶ Run", id="code-run")
        self._debug_button = Button("Debug", id="code-debug-start")
        self._reconnect_button = Button("Reconnect", id="code-reconnect")
        self._reconnect_button.display = False
        self._stop_button = Button("Stop", id="code-stop", disabled=True)
        self._run_state = Static(
            "Ready. Select a profile and press F5.", id="code-run-state", markup=False
        )
        self._branch = Static("", id="code-branch", markup=False)
        self._branch.display = False
        self._pane = CodeTerminal(
            self._run_context_state, id="code-terminal",
            escape_hook=lambda: self.query_one(DataTable).focus(),
        )
        profiles = Vertical(
            # The count sits at the right end of the title row.
            Horizontal(
                Static("PROFILES", id="code-title"),
                Static("", id="code-count"),
                id="code-title-row", classes="pane-title",
            ),
            Static("", id="code-status", markup=False),
            DataTable(id="code-projects", cursor_type="row", zebra_stripes=True,
                      show_header=False),
            PaneSplitter(id="code-profiles-splitter"),
            id="code-profiles-pane",
        )
        # The debug panel is built first so it can sit beside the editor inside the browser.
        self._debug = CodeDebug(None, self._state, self._debug_finished)
        self._debug.border_title = "Debug"
        self._bottom = Vertical(self._pane, self._debug.output, id="code-bottom")
        self._browser = SourceBrowser(
            sidebar_header=profiles, editor_side=self._debug, bottom=self._bottom
        )
        self._debug.browser = self._browser

    def compose(self) -> ComposeResult:
        with Horizontal(id="code-actions"):
            yield self._run_button
            yield self._debug_button
            yield self._reconnect_button
            yield self._stop_button
            yield Button("↻ Reload", id="code-reload")
            yield self._run_state
            yield self._branch
        yield self._browser

    def toggle_terminal(self) -> None:
        """O collapses the bottom area: run terminal or debug output."""
        self._bottom.display = not self._bottom.display
        if not self._bottom.display and self.app.focused in self._bottom.query("*"):
            self.query_one(DataTable).focus()

    def _show_bottom(self) -> None:
        self._bottom.display = True

    def on_mount(self) -> None:
        # Wide enough for the cursor highlight to span the sidebar.
        self.query_one(DataTable).add_column("Profile", width=26)
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
                table.add_row(profile.name, key=profile.name)
            keys = [profile.name for profile in profiles]
            if selected in keys:
                table.move_cursor(row=keys.index(selected))
            # The count lives in the title; the status line only explains problems.
            message = (
                ""
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
                table.add_row(profile.name, key=profile.name)
            message = str(error)
        status = self.query_one("#code-status", Static)
        status.update(message)
        status.display = bool(message)
        self.query_one("#code-count", Static).update(
            str(len(self._profiles)) if self._profiles else ""
        )
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
        # The status line describes the view that is actually shown.
        if self._apply_view(profile) == "debug" and debug_context is not None:
            self._state(debug_context.state)
        elif run_context is not None:
            self._state(run_context.state)
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

    def _apply_view(self, profile):
        """Show exactly one of the run terminal or the debug panel for the selection."""
        run = self._pane.selected_context
        debug = self._debug.selected
        run_live = bool(run and (run.pending or run.active or run.stopping))
        debug_live = bool(debug and (
            debug.active or debug.stopping or debug.unexpected_disconnect
        ))
        if debug_live:
            view = "debug"
        elif run_live or debug is None:
            view = "run"
        elif run is None:
            view = "debug"
        else:
            view = self._last_view.get(profile.name if profile else "", "run")
        # The side panel is for live sessions; a finished one keeps only its output below.
        self._debug.display = view == "debug" and debug_live
        self._debug.output.display = view == "debug"
        self._pane.display = view == "run" and run is not None
        return view

    def _state(self, message):
        self._run_state.update(message)

    def _debug_finished(self, unexpected_disconnect=False):
        self._reconnect_button.display = bool(unexpected_disconnect)
        debug_context = self._debug.selected
        if debug_context is not None and not self._shutting_down:
            # A session can end on its own (e.g. after Continue); drop the empty side panel.
            if self._apply_view(debug_context.profile) == "debug":
                self._state(debug_context.state)
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
        if debug_selected:
            branch = self._launch_branches.get(debug_context.profile.name)
        elif run_selected:
            branch = self._launch_branches.get(run_context.profile.name)
        else:
            profile = self._highlighted_profile()
            branch = current_branch(profile.root) if profile is not None else None
        self._branch.update(f"⎇ {branch}" if branch else "")
        self._branch.display = bool(branch)

    def _highlighted_profile(self):
        # Session callbacks can arrive while the area unmounts; there is nothing to show then.
        tables = self.query(DataTable)
        if not tables or not tables.first().row_count:
            return None
        table = tables.first()
        return self._profiles.get(table.ordered_rows[table.cursor_row].key.value)

    def _remember_launch_branch(self, profile):
        self._launch_branches[profile.name] = current_branch(profile.root)

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
            self._last_view[profile.name] = "debug"
            self._debug.select_context(debug_context)
            self._pane.display = False
            self._state(debug_context.state)
            self._debug.resume("continue_execution")
            self._sync_controls()
            return
        run_context = self._pane.contexts.get(profile.name)
        if run_context is not None and (
            run_context.pending or run_context.active or run_context.stopping
        ):
            self._last_view[profile.name] = "run"
            self._pane.select_profile(profile)
            self._debug.display = False
            self._state(run_context.state)
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
        self._last_view[profile.name] = "run"
        self._debug.display = False
        context, created = self._pane.prepare_profile(profile)
        self._pane.display = True
        self._show_bottom()
        if created:
            self._remember_launch_branch(profile)
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
        self._last_view[profile.name] = "debug"
        self._remember_launch_branch(profile)
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
            self._last_view[profile.name] = "run"
            self._pane.select_profile(profile)
            self._pane.display = True
            self._debug.display = False
            self._state(run_context.state)
            self._sync_controls()
            return
        debug_context = self._debug.context_for(profile)
        if debug_context is not None and debug_context.active:
            self._last_view[profile.name] = "debug"
            self._debug.select_context(debug_context)
            self._pane.display = False
            self._state(debug_context.state)
            self._sync_controls()
            return
        self._last_view[profile.name] = "debug"
        self._pane.display = False
        self._show_bottom()
        self._remember_launch_branch(profile)
        self._debug.start(profile)
        self._sync_controls()

    def check_action(self, action, parameters):
        if action in {"stop_run", "resize_profiles"}:
            focused = self.app.focused
            # A text field or a live terminal types the letter instead.
            if isinstance(focused, Input) or (
                isinstance(focused, TerminalPane) and focused.active
            ):
                return False
        if action == "focus_pane":
            focused = self.app.focused
            # Text fields and live terminals keep Ctrl+arrows for moving by word.
            if isinstance(focused, Input) or (
                isinstance(focused, TerminalPane) and focused.active
            ):
                return False
        return True

    def action_focus_pane(self, step: int) -> None:
        panes = [pane for selector in PANES for pane in self.query(selector)
                 if pane.display and pane.focusable]
        if not panes:
            return
        focused = self.app.focused
        current = next((index for index, pane in enumerate(panes)
                        if focused is pane or (focused is not None and pane in focused.ancestors)),
                       None)
        if current is None:
            # From a button or another widget, start at the profiles.
            panes[0].focus()
            return
        # Past either end, wrap around to the other one.
        panes[(current + step) % len(panes)].focus()

    def toggle_breakpoint(self):
        browser = self.query_one(SourceBrowser)
        if browser.file_path is None:
            self.app.notify(
                "Open a source file before toggling a breakpoint.", severity="warning"
            )
            return
        browser.toggle_breakpoint()

    def edit_breakpoint(self):
        browser = self.query_one(SourceBrowser)
        if browser.file_path is None:
            self.app.notify(
                "Open a source file before editing a breakpoint.", severity="warning"
            )
            return
        browser.edit_breakpoint()

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
            if task.cancelled():
                context.state = "Stopped"
            elif task.exception() is not None:
                # Never hide a failed start behind a Ready state.
                context.state = f"Unable to run {profile.name}: {task.exception()}"
            else:
                context.state = f"Ready: {profile.name}"
            if self._pane.selected_context is context:
                self._state(context.state)
                self._sync_controls()

    def action_resize_profiles(self, rows: int) -> None:
        self._set_profile_rows(self._profile_rows + rows)

    @on(PaneSplitter.Moved)
    def _splitter_moved(self, event) -> None:
        self._set_profile_rows(self._profile_rows + event.rows)

    def _set_profile_rows(self, rows: int) -> None:
        """Resize the profile list, leaving the file tree at least MIN_TREE_ROWS."""
        table = self.query_one("#code-projects", DataTable)
        limit = rows
        tree = self.query("#source-tree")
        if tree and table.size.height:
            # The list and the tree share the room left by the fixed rows around them.
            limit = table.size.height + tree.first().size.height - MIN_TREE_ROWS
        self._profile_rows = max(MIN_PROFILE_ROWS, min(rows, limit))
        table.styles.height = self._profile_rows

    async def action_stop_run(self) -> None:
        await self.stop()

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
