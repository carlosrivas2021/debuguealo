import asyncio
from contextlib import aclosing
from dataclasses import replace
from pathlib import Path

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import ConfigurationError, DebugPilotError
from debugpilot.core.models import ContainerInfo
from debugpilot.docker.compose import ComposeError, ComposePlan, ComposeProject, ComposeUpOptions
from debugpilot.storage.compose_projects import ComposeProjectStore
from debugpilot.storage.launch_profiles import LaunchProfile, LaunchProfileStore
from debugpilot.tui.container_list import ContainerRow, container_label, container_rows
from debugpilot.tui.log_viewer import LogViewer

ACTIVE_STATES = frozenset({"running", "paused", "restarting"})


class DebugPilotApp(App):
    """The terminal owns its UI tasks; Docker operations stay behind the engine."""

    TITLE = "DebugPilot"
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+l", "focus_logs", "Logs"),
        Binding("ctrl+r", "retry_logs", "Retry logs"),
        Binding("r", "restart_selected", "Restart"),
        Binding("R,shift+r", "rebuild_selected", "Build"),
        Binding("s", "stop_selected", "Stop"),
        Binding("ctrl+o", "compose", "Compose"),
        Binding("ctrl+n", "start_project", "Open Compose"),
        Binding("escape", "cancel_compose", show=False),
        *[
            Binding(key, "debugger_unavailable", show=False)
            for key in ("f5", "f9", "f10", "f11", "shift+f11")
        ],
    ]

    def __init__(
        self,
        engine: DebugPilotEngine,
        *,
        refresh_interval: float = 2,
        workspace: Path | None = None,
    ):
        super().__init__()
        self.engine = engine
        self.theme = "textual-dark"
        self.refresh_interval = max(0.05, refresh_interval)
        self.selected_container: ContainerInfo | None = None
        self.selected_project: str | None = None
        self._selection_key: str | None = None
        self._rows: dict[str, ContainerRow] = {}
        self._inventory: dict[str, ContainerInfo] = {}
        self._inventory_loaded = False
        self._show_all = False
        self._inventory_widths: dict[str, tuple[int, int]] = {}
        self._selection_changed = asyncio.Event()
        self._generation = 0
        self._selection_revision = 0
        self._group_signature: tuple[tuple[str, str], ...] = ()
        self._closing = False
        self._ui_tasks: list[asyncio.Task] = []
        self._stream_task: asyncio.Task | None = None
        self._compose_projects: dict[str, ComposeProject] = {}
        self._inline_plan: ComposePlan | None = None
        self._pending_stop: tuple[str, ...] = ()
        self._inline_service = None
        self._inline_task: asyncio.Task | None = None
        self._compose_store = ComposeProjectStore()
        self._compose_config_error: str | None = None
        self._launch_store: LaunchProfileStore | None = None
        self._launch_profiles: list[LaunchProfile] = []
        self._launch_error: str | None = None
        self._profile_choices: dict[str, str] = {}
        try:
            self._launch_store = LaunchProfileStore(workspace)
        except ConfigurationError as error:
            self._launch_error = str(error)
        try:
            self._saved_compose_projects = self._compose_store.load()
        except ConfigurationError as error:
            self._saved_compose_projects = {}
            self._compose_config_error = str(error)

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("DebugPilot  ·  Docker: connecting…", id="docker-state", markup=False)
            yield Button("Open Compose", id="open-compose")
            yield Button("Stop", id="stop-selected", variant="warning")
        yield Static("Launch profiles: loading…", id="launch-state", markup=False)
        with Horizontal(id="dashboard"):
            with Vertical(id="sidebar"):
                yield Checkbox("Show all", id="show-all")
                yield DataTable(id="containers", cursor_type="row", zebra_stripes=True)
                with Vertical(id="stopped-area"):
                    yield Static("STOPPED / INACTIVE", id="stopped-title", markup=False)
                    yield DataTable(id="stopped-containers", cursor_type="row", zebra_stripes=True)
                yield Static("No container selected", id="container-info", markup=False)
            with Vertical(id="logs-panel"):
                yield Static("Select a container", id="log-state", markup=False)
                yield LogViewer()
        yield Static(
            "Debugger / source / variables: not implemented yet (T4–T5).",
            id="debugger-state",
            markup=False,
        )
        with Horizontal(id="inline-compose"):
            yield Static("", id="inline-compose-message", markup=False)
            yield Button("Confirm", id="inline-compose-confirm", variant="warning")
            yield Button("Cancel", id="inline-compose-cancel")
        yield Footer()

    async def on_mount(self) -> None:
        if self._compose_config_error:
            self.notify(self._compose_config_error, severity="warning")
        table = self.query_one("#containers", DataTable)
        table.focus()
        await self.engine.start()
        self._ui_tasks = [
            asyncio.create_task(self._refresh_loop()),
            asyncio.create_task(self._selection_loop()),
        ]

    def on_resize(self) -> None:
        self.set_class(self.size.width < 100 or self.size.height < 28, "compact")
        self.call_after_refresh(self._resize_inventory)

    def _resize_inventory(self) -> None:
        if self._inventory_loaded and not self._closing:
            self._show_inventory(list(self._inventory.values()), force=True)

    def _render_inventory(self, table: DataTable, rows: list[ContainerRow]) -> None:
        viewport = table.content_region.width or self.query_one("#containers").content_region.width
        available = max(8, (viewport or 30) - table.styles.scrollbar_size_vertical - 4)
        state_width = min(10, available // 3)
        name_width = available - state_width
        widths = (name_width, state_width)
        if self._inventory_widths.get(table.id) != widths:
            table.clear(columns=True)
            table.add_column(
                Text("Project / container", overflow="ellipsis", no_wrap=True), width=name_width
            )
            table.add_column("State", width=state_width)
            self._inventory_widths[table.id] = widths
        else:
            table.clear()
        for row in rows:
            style = (
                "bold cyan"
                if row.container is None
                else ("green" if row.state == "running" else "yellow")
            )
            table.add_row(
                Text(
                    row.label,
                    style="bold" if row.container is None else "",
                    overflow="ellipsis",
                    no_wrap=True,
                ),
                Text(row.state, style=style, overflow="ellipsis", no_wrap=True),
                key=row.key,
            )

    async def _refresh_loop(self) -> None:
        while not self._closing:
            try:
                inventory = await self.engine.list_containers()
                self._update_launch_profiles(inventory)
                active = sum(item.state in ACTIVE_STATES for item in inventory)
                self.query_one("#docker-state", Static).update(
                    f"DebugPilot  ·  Docker: connected  ·  {active} active / {len(inventory)} total"
                )
                self._show_inventory(inventory)
            except DebugPilotError as error:
                self.query_one("#docker-state", Static).update(f"Docker unavailable: {error}")
                self._show_inventory([])
            except Exception:
                self.query_one("#docker-state", Static).update(
                    "Docker unavailable: unable to read inventory. Retrying…"
                )
                self._show_inventory([])
            await asyncio.sleep(self.refresh_interval)

    @on(Checkbox.Changed, "#show-all")
    def visibility_changed(self, event: Checkbox.Changed) -> None:
        self._show_all = event.value
        self._show_inventory(list(self._inventory.values()), force=True)

    def _update_launch_profiles(self, inventory: list[ContainerInfo]) -> None:
        if self._launch_store is None:
            self.query_one("#launch-state", Static).update(
                f"Launch profiles unavailable: {self._launch_error}"
            )
            return
        try:
            self._launch_store.register(inventory)
            self._launch_profiles = self._launch_store.profiles()
            self._launch_error = None
            pending = sum(profile.pending_reason is not None for profile in self._launch_profiles)
            self.query_one("#launch-state", Static).update(
                f"Launch: {len(self._launch_profiles) - pending} ready / {pending} pending · "
                f"Ctrl+O · {self._launch_store.path}"
            )
            self.query_one("#launch-state").tooltip = str(self._launch_store.path)
        except (ConfigurationError, OSError) as error:
            self._launch_error = str(error)
            self._launch_profiles = []
            self.query_one("#launch-state", Static).update(
                f"Launch profiles: {error} · logs remain available"
            )

    def _project_from_profile(self, profile: LaunchProfile) -> ComposeProject:
        if self._launch_store is None:
            raise ConfigurationError("Launch profiles are unavailable.")
        resolved = self._launch_store.resolve(profile)
        if resolved is None or profile.pending_reason:
            raise ConfigurationError(
                profile.pending_reason or "Launch profile needs configuration."
            )
        values = resolved.up
        up = (
            None
            if values is None
            else ComposeUpOptions(
                build=values.get("build", False),
                detach=values.get("detach", True),
                force_recreate=values.get("forceRecreate", False),
            )
        )
        return ComposeProject.create(
            resolved.workspace,
            resolved.files,
            resolved.project_name,
            project_directory=resolved.project_directory,
            process_cwd=resolved.cwd,
            environment_files=resolved.environment_files,
            up=up,
        )

    def _profile_selected(self, name: str, project: str) -> None:
        self._profile_choices[project] = name

    def _dialog_profiles(self, project: str | None = None) -> list[LaunchProfile]:
        if self._launch_store is None:
            return []
        try:
            return self._launch_store.profiles(project)
        except ConfigurationError as error:
            self._launch_error = str(error)
            self.notify(str(error), severity="warning")
            return []

    def _show_inventory(self, inventory: list[ContainerInfo], *, force: bool = False) -> None:
        current = {item.id: item for item in inventory}
        if self._inventory_loaded and current == self._inventory and not force:
            return
        if isinstance(self.focused, DataTable) and self.focused.id in {
            "containers",
            "stopped-containers",
        }:
            # Layout refresh may run before the highlighted-row event is handled.
            self._select_focused_row(self.focused)
        self._inventory_loaded = True
        previous_key, previous_project = self._selection_key, self.selected_project
        previous_container = self.selected_container
        self._inventory = current
        rows = container_rows([item for item in inventory if item.state in ACTIVE_STATES])
        inactive = [item for item in inventory if item.state not in ACTIVE_STATES]
        self.query_one("#show-all", Checkbox).label = f"Show all ({len(inactive)} stopped)"
        stopped = (
            [replace(row, key="stopped:" + row.key) for row in container_rows(inactive)]
            if self._show_all
            else []
        )
        self.query_one("#stopped-area").display = self._show_all
        all_rows = [*rows, *stopped]
        self._rows = {row.key: row for row in all_rows}
        for selector, entries in (("#containers", rows), ("#stopped-containers", stopped)):
            table = self.query_one(selector, DataTable)
            self._render_inventory(table, entries)
        selected = self._rows.get(previous_key)
        if selected is None and previous_container is not None:
            selected = next(
                (
                    row
                    for row in all_rows
                    if row.container is not None and row.container.id == previous_container.id
                ),
                None,
            )
        if selected is None and previous_project is not None:
            selected = self._rows.get(f"project:{previous_project}")
        if selected is None and previous_key is None:
            # Preserve initial auto-selection of a service, but never silently
            # open an unrelated stream when an existing selection disappears.
            selected = next((row for row in rows if row.container is not None), None)
        selected = selected or next(iter(all_rows), None)
        if selected:
            table = self.query_one(
                "#stopped-containers" if selected.key.startswith("stopped:") else "#containers",
                DataTable,
            )
            entries = stopped if selected.key.startswith("stopped:") else rows
            table.move_cursor(row=entries.index(selected))
            self._select(selected.container, project=selected.project, row_key=selected.key)
        else:
            self._select(None)

    @on(DataTable.RowHighlighted, "#containers")
    @on(DataTable.RowHighlighted, "#stopped-containers")
    def container_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._select_focused_row(event.data_table, expected_key=event.row_key.value)

    @on(DataTable.RowSelected, "#containers")
    @on(DataTable.RowSelected, "#stopped-containers")
    def container_selected(self, event: DataTable.RowSelected) -> None:
        self._select_focused_row(event.data_table, expected_key=event.row_key.value)

    @on(events.DescendantFocus, "#containers")
    @on(events.DescendantFocus, "#stopped-containers")
    def inventory_focused(self, event: events.DescendantFocus) -> None:
        # Entering a table need not move its cursor or emit RowHighlighted.
        self._select_focused_row(event.widget)

    def _select_focused_row(self, table: DataTable, *, expected_key: str | None = None) -> None:
        if table.row_count and table.has_focus and table.is_mounted and not self._closing:
            # Rebuilding inventory can enqueue old highlight events; accept only
            # the row that is still under the cursor, not an obsolete selection.
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            if expected_key is None or expected_key == key:
                row = self._rows.get(key)
                if row is not None:
                    if row.key != self._selection_key:
                        self._selection_revision += 1
                    table.tooltip = Text(
                        f"{row.container.name if row.container else row.label.strip()}\n"
                        f"State: {row.state}\nService: {row.service or '—'}"
                    )
                    self._select(row.container, project=row.project, row_key=row.key)

    def _select(
        self,
        item: ContainerInfo | None,
        *,
        project: str | None = None,
        row_key: str | None = None,
        force: bool = False,
    ) -> None:
        old = (
            self.selected_container,
            self.selected_project,
            self._selection_key,
            self._group_signature,
        )
        self.selected_container = item
        self.selected_project = item.compose_project if item is not None else project
        self._selection_key = row_key or (f"container:{item.id}" if item is not None else None)
        self._group_signature = tuple((member.id, member.state) for member in self._group_members())
        empty_detail = (
            "No active containers. Enable Show all to inspect stopped containers."
            if self._inventory and not self._show_all
            else "No containers found; waiting for Docker inventory."
        )
        if self.selected_project:
            count = sum(
                value.compose_project == self.selected_project for value in self._inventory.values()
            )
            empty_detail = (
                f"Compose project: {self.selected_project}\n{count} containers\n"
                "Combined project logs; select a service to isolate it."
            )
        elif self._selection_key == "standalone:":
            empty_detail = (
                "Standalone containers have no Compose project. Select a container for logs."
            )
        self.query_one("#container-info", Static).update(
            Text(
                f"{item.image}\n{item.id[:12]} · {item.state}\n"
                f"Compose: {item.compose_project or '—'} / {item.compose_service or '—'}"
            )
            if item
            else Text(empty_detail)
        )
        if force or old != (
            item,
            self.selected_project,
            self._selection_key,
            self._group_signature,
        ):
            self._generation += 1
            self._selection_changed.set()

    def _group_members(self) -> tuple[ContainerInfo, ...]:
        if self.selected_container is not None or not self.selected_project:
            return ()
        stopped = (self._selection_key or "").startswith("stopped:")
        return tuple(
            row.container
            for row in self._rows.values()
            if row.container is not None
            and row.project == self.selected_project
            and row.key.startswith("stopped:") == stopped
        )

    async def _stop_stream(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
            await asyncio.gather(self._stream_task, return_exceptions=True)
            self._stream_task = None

    async def _selection_loop(self) -> None:
        try:
            while not self._closing:
                await self._selection_changed.wait()
                self._selection_changed.clear()
                await self._stop_stream()
                if self._closing:
                    break
                # Selection may have changed while the old stream was closing.
                self._selection_changed.clear()
                item, generation = self.selected_container, self._generation
                self.query_one(LogViewer).action_clear_logs()
                members = self._group_members()
                if item is None and members:
                    if len(members) > 32:
                        self.query_one("#log-state", Static).update(
                            "Project has over 32 containers; select a service for logs."
                        )
                    else:
                        self.query_one("#log-state", Static).update(
                            f"Project · {self.selected_project} · {len(members)} services"
                        )
                        self._stream_task = asyncio.create_task(
                            self._consume_group(members, generation, self.selected_project)
                        )
                elif item is None:
                    message = (
                        f"Project · {self.selected_project} · select a service for logs"
                        if self.selected_project
                        else "No active containers; enable Show all"
                        if self._inventory and not self._show_all
                        else "No container selected"
                    )
                    self.query_one("#log-state", Static).update(message)
                else:
                    self.query_one("#log-state", Static).update(f"Logs · {item.name}")
                    self._stream_task = asyncio.create_task(self._consume(item, generation))
        finally:
            await self._stop_stream()

    async def _consume_group(
        self, members: tuple[ContainerInfo, ...], generation: int, project: str
    ) -> None:
        labels = {item.id: container_label(item) for item in members}
        for item in members:
            if list(labels.values()).count(labels[item.id]) > 1:
                labels[item.id] = item.name
        statuses = {item.id: "following" for item in members}

        async def consume(item: ContainerInfo) -> None:
            message = await self._consume(item, generation, source=labels[item.id])
            statuses[item.id] = message
            if self._generation == generation and not self._closing:
                summary = "; ".join(f"{labels[key]}: {value}" for key, value in statuses.items())
                self.query_one("#log-state", Static).update(f"Project · {project} · {summary}")

        await asyncio.gather(*(consume(item) for item in members))

    async def _consume(
        self, item: ContainerInfo, generation: int, *, source: str | None = None
    ) -> str:
        try:
            async with aclosing(
                self.engine.stream_logs(
                    item.id, tail=100, follow=item.state == "running", current_run=True
                )
            ) as entries:
                async for entry in entries:
                    if self._generation == generation and not self._closing:
                        if source is not None:
                            text = f"[{source}] {entry.text}"
                            entry = entry.model_copy(
                                update={
                                    "text": text[:16_384],
                                    "truncated": entry.truncated or len(text) > 16_384,
                                }
                            )
                        self.query_one(LogViewer).append(entry)
            message = f"Logs · {item.name} · stream ended (Ctrl+R to retry)"
        except DebugPilotError as error:
            message = f"Logs · {item.name} · {error} (Ctrl+R to retry)"
        except Exception:
            message = f"Logs · {item.name} · unable to read logs (Ctrl+R to retry)"
        if source is None and self._generation == generation and not self._closing:
            self.query_one("#log-state", Static).update(message)
        return message

    async def on_unmount(self) -> None:
        self._closing = True
        if self._inline_task is not None:
            self._inline_task.cancel()
            await asyncio.gather(self._inline_task, return_exceptions=True)
        self._selection_changed.set()
        # Let the selection owner finish any pending stream cleanup rather than
        # cancelling it a second time in the middle of an async generator finally.
        if self._ui_tasks:
            self._ui_tasks[0].cancel()
            await asyncio.gather(*self._ui_tasks, return_exceptions=True)
        await self.engine.close()

    def action_focus_logs(self) -> None:
        self.query_one("#log-entries", DataTable).focus()

    def action_retry_logs(self) -> None:
        if self.selected_container or self.selected_project:
            self._select(
                self.selected_container,
                project=self.selected_project,
                row_key=self._selection_key,
                force=True,
            )

    def action_debugger_unavailable(self) -> None:
        self.notify("Debugger controls arrive with DAP integration (T4–T5).")

    def action_compose(self) -> None:
        self._open_compose()

    @on(Button.Pressed, "#open-compose")
    def action_start_project(self) -> None:
        from debugpilot.docker.compose import ComposeService
        from debugpilot.tui.compose_dialog import ComposeDialog

        if self._inline_task is not None and not self._inline_task.done():
            self.notify("A Compose operation is already running.", severity="warning")
            return
        self._dismiss_inline_compose()
        profiles = self._dialog_profiles()
        self.push_screen(
            ComposeDialog(
                ComposeService(self.engine.settings),
                None,
                initial_action="start",
                browse_on_mount=not profiles,
                remember_project=self._remember_compose_project,
                launch_profiles=profiles,
                resolve_profile=self._project_from_profile,
                profile_selected=self._profile_selected,
                launch_store=self._launch_store,
            )
        )

    def action_restart_selected(self) -> None:
        self._open_compose("restart", contextual=True)

    def _remember_compose_project(self, project: ComposeProject) -> None:
        self._compose_projects[project.project_name] = project
        try:
            self._compose_store.save(project)
        except ConfigurationError as error:
            self.notify(
                f"Compose succeeded, but routes were not saved: {error}", severity="warning"
            )

    def action_rebuild_selected(self) -> None:
        self._open_compose("rebuild", contextual=True)

    def _open_compose(self, initial_action: str = "recreate", *, contextual: bool = False) -> None:
        from debugpilot.docker.compose import ComposeService
        from debugpilot.tui.compose_dialog import ComposeDialog

        if self._inline_task is not None and not self._inline_task.done():
            self.notify("A Compose operation is already running.", severity="warning")
            return
        self._dismiss_inline_compose()
        # Resolve the visibly focused cursor even if a focus event is still queued.
        if isinstance(self.focused, DataTable) and self.focused.id in {
            "containers",
            "stopped-containers",
        }:
            self._select_focused_row(self.focused)

        if contextual and (
            not self.selected_project
            or (self.selected_container is not None and not self.selected_container.compose_service)
        ):
            self.notify(
                "Select a Compose project or service before restarting or rebuilding.",
                severity="warning",
            )
            return
        remembered_project = self._compose_projects.get(self.selected_project)
        profiles = self._dialog_profiles(self.selected_project)
        if (
            profiles
            and all(profile.dynamic for profile in profiles)
            and (
                remembered_project is not None
                or self.selected_project in self._saved_compose_projects
            )
        ):
            # Explicitly chosen session/legacy routes win over live detection hints.
            profiles = []
        if contextual and self._launch_error:
            self.notify(
                f"Fix launch profiles before running Compose: {self._launch_error}",
                severity="warning",
            )
            return
        if profiles:
            choice = self._profile_choices.get(self.selected_project)
            candidates = [p for p in profiles if p.name == choice] if choice else profiles
            if len(candidates) == 1:
                try:
                    remembered_project = self._project_from_profile(candidates[0])
                except (ConfigurationError, ComposeError) as error:
                    remembered_project = None
                    if contextual:
                        self.notify(
                            f"Launch profile pending: {error} Edit {self._launch_store.path}.",
                            severity="warning",
                        )
                        return
            elif contextual:
                self.notify("Choose a launch profile with Ctrl+O first.", severity="warning")
                return
        if (
            not profiles
            and remembered_project is None
            and self.selected_project in self._saved_compose_projects
        ):
            try:
                remembered_project = self._saved_compose_projects[self.selected_project].resolve()
            except ComposeError:
                self.notify(
                    "Saved Compose files are unavailable. Choose the project configuration again.",
                    severity="warning",
                )
        if contextual:
            if remembered_project is None:
                self.notify("Configure this project once with Ctrl+O first.", severity="warning")
                return
            service = ComposeService(self.engine.settings)
            target = self.selected_container.compose_service if self.selected_container else None
            try:
                self._inline_plan = service.preview(remembered_project, initial_action, target)
            except ComposeError as error:
                self.notify(f"{error} Use Ctrl+O to review the configuration.", severity="warning")
                return
            self._inline_service = service
            scope = target or "all services, including stopped"
            verb = "Restart" if initial_action == "restart" else "Rebuild/recreate"
            self.query_one("#inline-compose-message", Static).update(
                f"{verb} {remembered_project.project_name} / {scope}?"
            )
            self.query_one("#inline-compose").tooltip = self._inline_plan.display
            self.query_one("#inline-compose").display = True
            self.query_one("#inline-compose-confirm", Button).disabled = False
            self.query_one("#inline-compose-cancel", Button).label = "Cancel"
            self.query_one("#inline-compose-confirm", Button).focus()
            return
        self._dismiss_inline_compose()
        self.push_screen(
            ComposeDialog(
                ComposeService(self.engine.settings),
                self.selected_container,
                selected_project=self.selected_project,
                initial_action=initial_action,
                remembered_project=remembered_project,
                quick=contextual,
                remember_project=self._remember_compose_project,
                launch_profiles=profiles,
                resolve_profile=self._project_from_profile,
                profile_selected=self._profile_selected,
                launch_store=self._launch_store,
            )
        )

    def _dismiss_inline_compose(self) -> None:
        self._inline_plan = None
        self._pending_stop = ()
        self.query_one("#inline-compose").display = False

    @on(Button.Pressed, "#stop-selected")
    def action_stop_selected(self) -> None:
        if self._inline_task is not None and not self._inline_task.done():
            self.notify("An operation is already running.", severity="warning")
            return
        if isinstance(self.focused, DataTable) and self.focused.id in {
            "containers",
            "stopped-containers",
        }:
            self._select_focused_row(self.focused)
        members = (
            [self.selected_container]
            if self.selected_container is not None
            else list(self._group_members())
            if self.selected_project
            else []
        )
        targets = tuple(c.id for c in members if c.state in ACTIVE_STATES)
        if not targets or len(targets) > 32:
            self.notify(
                "Select 1–32 active containers; select a service for larger groups.",
                severity="warning",
            )
            return
        self._dismiss_inline_compose()
        self._pending_stop = targets
        scope = self.selected_container.name if self.selected_container else self.selected_project
        self.query_one("#inline-compose-message", Static).update(
            f"Stop {scope} / {len(targets)} active container(s)? "
            "No containers or volumes are removed."
        )
        self.query_one("#inline-compose").tooltip = "Pinned targets:\n" + "\n".join(targets)
        self.query_one("#inline-compose").display = True
        self.query_one("#inline-compose-confirm", Button).disabled = False
        self.query_one("#inline-compose-cancel", Button).label = "Cancel"
        self.query_one("#inline-compose-confirm", Button).focus()

    @on(Button.Pressed, "#inline-compose-confirm")
    def confirm_inline_compose(self) -> None:
        if self._pending_stop and (self._inline_task is None or self._inline_task.done()):
            targets, self._pending_stop = self._pending_stop, ()
            self.query_one("#inline-compose-confirm", Button).disabled = True
            self.query_one("#inline-compose-cancel", Button).label = "Cancel wait"
            self.query_one("#inline-compose-message", Static).update(
                f"Stopping {len(targets)} pinned container(s)…"
            )
            self._inline_task = asyncio.create_task(self._run_stop(targets))
            return
        if self._inline_plan is None or (
            self._inline_task is not None and not self._inline_task.done()
        ):
            return
        plan, self._inline_plan = self._inline_plan, None
        self.query_one("#inline-compose-confirm", Button).disabled = True
        self.query_one("#inline-compose-cancel", Button).label = "Stop CLI"
        self.query_one("#inline-compose-message", Static).update(
            f"Running {plan.action}: {plan.project.project_name} / {plan.service or 'all services'}"
        )
        self._inline_task = asyncio.create_task(self._run_inline_compose(plan))

    async def _run_stop(self, targets: tuple[str, ...]) -> None:
        try:
            result = await self.engine.stop_containers(targets, confirmed=True)
            details = "; ".join(f"{key[:12]}: {value}" for key, value in result.failed.items())
            self.notify(
                f"Stop finished: {len(result.stopped)} stopped, "
                f"{len(result.failed)} failed/unknown. " + details[:500],
                severity="warning" if result.failed else "information",
            )
            inventory = await self.engine.list_containers()
            if not self._closing:
                self._update_launch_profiles(inventory)
                self._show_inventory(inventory)
        except asyncio.CancelledError:
            if not self._closing:
                self.notify(
                    "Stop wait cancelled; Docker may still stop targets. No rollback.",
                    severity="warning",
                )
        except Exception:
            if not self._closing:
                self.notify(
                    "Stop outcome is unknown. Inspect Docker before retrying.", severity="warning"
                )
        finally:
            if not self._closing:
                self._dismiss_inline_compose()
                self.query_one("#containers", DataTable).focus()

    async def _run_inline_compose(self, plan: ComposePlan) -> None:
        selection = self.selected_container
        project, revision = self.selected_project, self._selection_revision
        try:
            result = await self._inline_service.run(plan, confirmed=True)
            if result.exit_code == 0:
                self._remember_compose_project(plan.project)
                await self._refresh_compose_logs(plan, selection, project, revision)
            self.notify(
                f"Compose exited {result.exit_code}: {plan.project.project_name} / "
                f"{plan.service or 'all services'}. "
                + ("" if result.exit_code == 0 else "Inspect Docker before retrying."),
                severity="information" if result.exit_code == 0 else "warning",
            )
        except asyncio.CancelledError:
            if not self._closing:
                self.notify(
                    "CLI stopped; Docker changes may remain. No rollback.", severity="warning"
                )
        except ComposeError as error:
            self.notify(str(error), severity="warning")
        except Exception:
            self.notify("Compose failed. Inspect Docker before retrying.", severity="warning")
        finally:
            if not self._closing:
                self._dismiss_inline_compose()
                self.query_one("#containers", DataTable).focus()

    async def _refresh_compose_logs(
        self, plan: ComposePlan, selection: ContainerInfo | None, project: str | None, revision: int
    ) -> None:
        try:
            inventory = await self.engine.list_containers()
        except Exception:
            self.notify(
                "Compose succeeded, but logs could not refresh. Use Ctrl+R to retry.",
                severity="warning",
            )
            return
        if self._closing:
            return
        self._show_inventory(inventory)
        if (
            revision == self._selection_revision
            and project == plan.project.project_name
            and selection is not None
            and (plan.service is None or selection.compose_service == plan.service)
        ):
            # Rebuild replaces IDs; a temporary stopped state may also hide the row.
            candidates = [
                row
                for row in self._rows.values()
                if row.container is not None
                and row.project == project
                and row.container.compose_service == selection.compose_service
            ]
            target = next(
                (
                    row
                    for row in candidates
                    if row.container.id == selection.id or row.container.name == selection.name
                ),
                candidates[0] if len(candidates) == 1 else None,
            )
            if target is not None:
                table = self.query_one(
                    "#stopped-containers" if target.key.startswith("stopped:") else "#containers",
                    DataTable,
                )
                table.move_cursor(
                    row=next(
                        i for i, row in enumerate(table.ordered_rows) if row.key.value == target.key
                    )
                )
                self._select(target.container, project=target.project, row_key=target.key)
        if self.selected_project == plan.project.project_name and (
            self.selected_container is None
            or plan.service is None
            or self.selected_container.compose_service == plan.service
        ):
            # Reuse the selection owner so old streams close before the buffer resets.
            self.action_retry_logs()

    @on(Button.Pressed, "#inline-compose-cancel")
    def action_cancel_compose(self) -> None:
        if self._inline_task is not None and not self._inline_task.done():
            self._inline_task.cancel()
        else:
            self._dismiss_inline_compose()
            self.query_one("#containers", DataTable).focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "cancel_compose" and isinstance(self.screen, ModalScreen):
            return False
        if action in {"compose", "start_project"} and (
            self._inline_task is not None and not self._inline_task.done()
        ):
            return False
        if action in {
            "quit",
            "retry_logs",
            "compose",
            "focus_logs",
            "restart_selected",
            "rebuild_selected",
            "stop_selected",
            "start_project",
        } and isinstance(self.screen, ModalScreen):
            return False
        if action in {
            "quit",
            "retry_logs",
            "restart_selected",
            "rebuild_selected",
            "stop_selected",
        } and isinstance(self.focused, Input):
            return False
        return True
