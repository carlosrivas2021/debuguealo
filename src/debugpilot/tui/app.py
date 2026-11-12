import asyncio
import hashlib
import json
import re
from contextlib import aclosing
from dataclasses import dataclass, replace
from pathlib import Path

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import ConfigurationError, DebugPilotError
from debugpilot.core.models import ContainerInfo, ContainerStats, LogEntry, cpu_percent
from debugpilot.docker.compose import ComposeError, ComposePlan, ComposeProject, ComposeUpOptions
from debugpilot.docker.diagnostics import default_endpoint
from debugpilot.storage.compose_projects import ComposeProjectStore
from debugpilot.storage.launch_profiles import LaunchProfile, LaunchProfileStore, profile_services
from debugpilot.tui.code_workspace import CodeWorkspace
from debugpilot.tui.compose_output import ProjectOutputBuffers
from debugpilot.tui.container_details import ContainerDetails, ProjectOverview, published_ports
from debugpilot.tui.container_list import (
    ContainerRow,
    container_label,
    container_rows,
    group_style,
    state_glyph,
)
from debugpilot.tui.execution_console import ExecutionConsole
from debugpilot.tui.host_terminal import HostTerminal
from debugpilot.tui.log_viewer import LogViewer
from debugpilot.tui.terminal_view import TerminalPane

ACTIVE_STATES = frozenset({"running", "paused", "restarting"})


def _plan_scope(plan) -> str:
    """Describe a Compose target: one service, the profile's services, or everything."""
    service = getattr(plan, "service", None)
    if service:
        return service
    services = getattr(getattr(plan, "project", None), "services", ())
    if isinstance(services, tuple) and services:
        return ", ".join(services)
    return "all services"


def _selection_signature(item: ContainerInfo | None) -> ContainerInfo | None:
    """Selection identity for change detection; Docker's uptime text is ignored."""
    return item.model_copy(update={"status": ""}) if item is not None else None


@dataclass(eq=False)
class _ComposeRun:
    """State one Compose run owns, so concurrent runs never read each other's globals."""

    plan: ComposePlan
    service: object
    profile: LaunchProfile | None
    profile_key: str | None
    prefix: str
    selection: ContainerInfo | None
    selected_project: str | None
    revision: int

    @property
    def project(self) -> str:
        return self.plan.project.project_name


class DebugPilotApp(App):
    """The terminal owns its UI tasks; Docker operations stay behind the engine."""

    TITLE = "debugealo"
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+t", "toggle_area", "Containers/Code"),
        Binding("ctrl+l", "focus_logs", "Logs"),
        Binding("ctrl+r", "retry_logs", "Retry logs"),
        Binding("d", "show_container_details", "Details"),
        Binding("space", "toggle_project", "Expand/collapse"),
        Binding("c", "open_container_terminal", "Container shell"),
        Binding("h", "open_host_terminal", "Host Bash"),
        Binding("o", "toggle_host_terminal", "Host terminal"),
        Binding("r", "recreate_selected", "Recreate"),
        Binding("R,shift+r", "build_selected", "Build + Recreate"),
        Binding("s", "stop_selected", "Stop"),
        Binding("a", "refresh_aws_credentials", "AWS creds"),
        Binding("ctrl+o,ctrl+n", "open_launch_file", "Open launch.json"),
        Binding("escape", "cancel_compose", show=False),
        Binding("f5", "run_code", "Run code"),
        Binding("shift+f5", "debug_code", "Debug"),
        Binding("f9", "toggle_breakpoint", show=False),
        Binding("shift+f9", "edit_breakpoint", show=False),
        Binding("f10", "code_step_over", "Step over"),
        Binding("f11", "code_step_in", "Step in"),
        Binding("shift+f11", "code_step_out", "Step out"),
        # Containers only; Code has its own pane order. Text fields keep word movement.
        Binding("ctrl+left", "container_pane(-1)", "Pane ←"),
        Binding("ctrl+right", "container_pane(1)", "Pane →"),
        # macOS takes Ctrl+arrows for switching spaces; Option+arrows do the same here.
        Binding("alt+left", "container_pane(-1)", show=False),
        Binding("alt+right", "container_pane(1)", show=False),
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
        self._initial_inventory_selection_complete = False
        self._inventory_ownership_signature: frozenset[str] = frozenset()
        self._show_all = False
        self._collapsed_projects: set[str] = set()
        self._inventory_widths: dict[str, tuple[int, int, int]] = {}
        self._inventory_content: dict[str, tuple[tuple[str, str, str, str], ...]] = {}
        self._selection_changed = asyncio.Event()
        # Logs stream only on request and close again when the selected row changes.
        self._logs_requested = False
        self._generation = 0
        self._selection_revision = 0
        self._group_signature: tuple[tuple[str, str], ...] = ()
        self._closing = False
        self._ui_tasks: list[asyncio.Task] = []
        self._stream_task: asyncio.Task | None = None
        # Stats are polled only for the selected running container while its card shows.
        self._stats_target: str | None = None
        self._stats_previous: ContainerStats | None = None
        self._stats_wake = asyncio.Event()
        self._stats_task: asyncio.Task | None = None
        self._update_task: asyncio.Task | None = None
        self._compose_projects: dict[str, ComposeProject] = {}
        self._inline_plan: ComposePlan | None = None
        self._pending_stop: tuple[str, ...] = ()
        self._pending_credential_recreates: list = []
        self._inline_service = None
        # Credential refresh / batch recreate: exclusive with every other operation.
        self._credential_task: asyncio.Task | None = None
        # Latest Compose run task per project; runs of different projects overlap.
        self._compose_tasks: dict[str, asyncio.Task] = {}
        self._pending_retry_plan: ComposePlan | None = None
        self._pending_retry_fingerprint: str | None = None
        self._retry_decision: asyncio.Future | None = None
        # Mid-run consents take the inline bar one at a time, after pending previews.
        self._bar_lock = asyncio.Lock()
        self._bar_idle = asyncio.Event()
        self._compose_outputs = ProjectOutputBuffers(
            max_projects=8,
            max_entries=1000,
            max_bytes=1024 * 1024,
            protected=self._project_is_composing,
        )
        self._compose_output_visible = False
        # Global feedback of recent stops, replayed under every project's output.
        self._stop_output: list[LogEntry] = []
        # Stops run independently in the background; these targets are still in flight.
        self._stopping: set[str] = set()
        self._stop_tasks: set[asyncio.Task] = set()
        self._compose_store = ComposeProjectStore()
        self._compose_config_error: str | None = None
        self._launch_store: LaunchProfileStore | None = None
        self._launch_profiles: list[LaunchProfile] = []
        self._launch_rows: dict[str, LaunchProfile] = {}
        self._launch_child_rows: dict[str, tuple[LaunchProfile, ContainerInfo]] = {}
        self._selected_profile: LaunchProfile | None = None
        self._selected_profile_key: str | None = None
        self._selected_profile_name: str | None = None
        self._pending_profile: LaunchProfile | None = None
        self._pending_profile_key: str | None = None
        self._launch_loaded = False
        self._launch_open_task: asyncio.Task | None = None
        self._launch_error: str | None = None
        self._terminal_open_task: asyncio.Task | None = None
        self._terminal_pane: TerminalPane | None = None
        self._host_terminal_pane: TerminalPane | None = None
        self._container_terminal_pane: TerminalPane | None = None
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
        with Horizontal(id="area-navigation"):
            yield Button("Containers", id="area-containers", variant="primary")
            yield Button("Code", id="area-code")
            yield Button("Open code launch.json", id="open-code-launch")
        with Vertical(id="container-area"):
            yield from self._compose_containers()
        code = CodeWorkspace()
        code.display = False
        yield code
        yield Footer()

    @on(Button.Pressed, "#area-containers")
    @on(Button.Pressed, "#area-code")
    def switch_area(self, event: Button.Pressed) -> None:
        event.stop()
        code = event.button.id == "area-code"
        self.query_one("#container-area").display = not code
        self.query_one(CodeWorkspace).display = code
        self.query_one("#area-code", Button).variant = "primary" if code else "default"
        self.query_one("#area-containers", Button).variant = "default" if code else "primary"
        self.query_one("#code-projects" if code else "#launch-profiles", DataTable).focus()

    def action_toggle_area(self) -> None:
        code = self.query_one(CodeWorkspace).display
        self.query_one("#area-containers" if code else "#area-code", Button).press()

    @on(Button.Pressed, "#open-code-launch")
    def open_code_launch(self) -> None:
        self.query_one("#area-code", Button).press()
        self._open_area_launch(code=True)

    def _compose_containers(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("debugealo  ·  Docker: connecting…", id="docker-state", markup=False)
            yield Button("Open launch.json", id="open-launch-file")
            yield Button("Stop", id="stop-selected", variant="warning")
        yield Static("Launch profiles: loading…", id="launch-state", markup=False)
        with Horizontal(id="dashboard"):
            with VerticalScroll(id="sidebar"):
                with Vertical(id="launch-section"):
                    with Horizontal(id="active-container-heading"):
                        yield Static("PROJECTS / CONTAINERS", id="launch-title", markup=False)
                        yield Checkbox("Show all", id="show-all")
                    yield DataTable(id="launch-profiles", cursor_type="row", zebra_stripes=True)
                    with Horizontal(id="profile-actions"):
                        yield Button("Play / Recreate", id="profile-recreate", disabled=True)
                        yield Button("Build + Recreate", id="profile-build-recreate", disabled=True)
                    with Vertical(id="empty-welcome"):
                        yield Static(
                            "No saved launch profiles. Add a configuration in launch.json.",
                            id="empty-welcome-message",
                            markup=False,
                        )
                        yield Button(
                            "Open launch.json", id="welcome-open-launch", variant="primary"
                        )
                yield Static("No container selected", id="container-info", markup=False)
            with Vertical(id="right-panel"):
                with Vertical(id="container-shell"):
                    with Horizontal(id="container-shell-controls"):
                        yield Static(
                            "Container shell", id="container-terminal-context", markup=False
                        )
                        yield Button("Logs", id="container-shell-logs")
                        yield Button("Close terminal", id="container-terminal-close")
                    self._container_terminal_pane = TerminalPane(
                        id="container-terminal-pane", escape_hook=self._focus_terminal_selection
                    )
                    yield self._container_terminal_pane
                yield ContainerDetails(id="container-details")
                yield ProjectOverview(id="project-overview")
                with Vertical(id="logs-panel"):
                    yield Static("Select a container", id="log-state", markup=False)
                    yield LogViewer()
                # The Compose transcript is a card under the details; the project
                # list keeps the full height.
                # Starts collapsed; its own button expands it (no shortcut on purpose).
                yield ExecutionConsole(id="compose-console")
                # The host shell docks at the bottom of the right panel, under the output.
                host = HostTerminal(
                    id="host-terminal", escape_hook=self._focus_terminal_selection
                )
                host.display = False
                self._host_terminal_pane = self._terminal_pane = host.terminal_pane
                yield host
        with Horizontal(id="inline-compose"):
            yield Static("", id="inline-compose-message", markup=False)
            yield Button("Confirm", id="inline-compose-confirm", variant="warning")
            yield Button("Cancel", id="inline-compose-cancel")

    def on_load(self) -> None:
        # Textual's run_async installs asyncio.eager_task_factory, which runs a task's
        # first step inside create_task. Code here assigns tasks before they may run
        # (for example `context.start_task = create_task(...)` then a guard comparing
        # it with current_task()), so keep standard task semantics, as tests use.
        asyncio.get_running_loop().set_task_factory(None)

    async def on_mount(self) -> None:
        if self._compose_config_error:
            self.notify(self._compose_config_error, severity="warning")
        table = self.query_one("#launch-profiles", DataTable)
        table.focus()
        await self.engine.start()
        self._update_launch_profiles()
        self._ui_tasks = [
            asyncio.create_task(self._refresh_loop()),
            asyncio.create_task(self._selection_loop()),
        ]
        self._stats_task = asyncio.create_task(self._stats_loop())
        self._update_task = asyncio.create_task(self._announce_update())

    async def _announce_update(self) -> None:
        """Tell the user about a newer release; never blocks startup or fails it."""
        from debugpilot import __version__, update_check

        try:
            latest = await asyncio.to_thread(update_check.available_update)
        except Exception:  # an update hint must never break the dashboard
            return
        if latest and not self._closing:
            self.notify(
                f"debugealo {latest} is available (you have {__version__}). "
                f"Update with: {update_check.UPDATE_COMMAND}",
                title="Update available",
                timeout=15,
            )

    def on_resize(self) -> None:
        self.set_class(self.size.width < 100 or self.size.height < 28, "compact")
        self.call_after_refresh(self._resize_inventory)

    def _resize_inventory(self) -> None:
        if self._inventory_loaded and not self._closing:
            # A focus/highlight event may still be queued when resize redraws rows.
            # Preserve the visible cursor in the active selection area, not merely
            # the last delivered selection event.
            key = self._selection_key or ""
            if key.startswith(("profile:", "profile-child:")):
                table = self.query_one("#launch-profiles", DataTable)
                if table.row_count:
                    cursor_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                    profile = self._launch_rows.get(cursor_key)
                    child = self._launch_child_rows.get(cursor_key)
                    if profile is not None:
                        self._select_launch_profile(cursor_key, profile)
                    elif child is not None:
                        self._select_launch_child(cursor_key, *child)
            elif key:
                table = self.query_one(
                    "#launch-profiles",
                    DataTable,
                )
                if table.row_count:
                    cursor_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                    row = self._rows.get(cursor_key)
                    if row is not None:
                        self._select(row.container, project=row.project, row_key=row.key)
            self._show_inventory(list(self._inventory.values()), force=True)

    def _render_inventory(self, table: DataTable, rows: list[ContainerRow]) -> bool:
        viewport = (
            table.content_region.width or self.query_one("#launch-profiles").content_region.width
        )
        # Three columns each have left/right cell padding; reserve scrollbar space
        # even while hidden so it can appear without overflowing the same columns.
        available = max(
            3, (viewport or 30) - table.styles.scrollbar_size_vertical - 6 * table.cell_padding
        )
        # State is a glyph or a short "n/m" counter, so ports and names get the room.
        state_width = min(5, available - 2)
        port_width = min(15, max(1, available - state_width - 18))
        name_width = max(1, available - state_width - port_width)
        widths = (name_width, port_width, state_width)
        content = tuple(
            (row.key, row.label, row.state, published_ports(row.container) if row.container else "")
            for row in rows
        )
        if (
            self._inventory_widths.get(table.id) == widths
            and self._inventory_content.get(table.id) == content
        ):
            return False
        if self._inventory_widths.get(table.id) != widths:
            table.clear(columns=True)
            table.add_column(
                Text("Project / container", overflow="ellipsis", no_wrap=True), width=name_width
            )
            table.add_column(
                Text("Published ports", overflow="ellipsis", no_wrap=True), width=port_width
            )
            table.add_column("State", width=state_width)
            self._inventory_widths[table.id] = widths
        else:
            table.clear()
        for row in rows:
            if row.container is None:
                label_style = "bold #a9c2cc"
                running, _, total = row.state.partition("/")
                state = Text(
                    row.state,
                    style=(
                        group_style(int(running), int(total))
                        if running.isdigit() and total.isdigit()
                        else "bold yellow"
                    ),
                    justify="right",
                )
                ports = ""
            else:
                active = row.container.state in ACTIVE_STATES
                label_style = "" if active else "bright_black"
                glyph, color = state_glyph(row.container.state)
                state = Text(glyph, style=color, justify="center")
                ports = published_ports(row.container)
                if ports == "None published":
                    ports = "—"
            table.add_row(
                Text(row.label, style=label_style, overflow="ellipsis", no_wrap=True),
                Text(
                    ports,
                    style="bright_black" if ports == "—" else "cyan",
                    overflow="ellipsis",
                    no_wrap=True,
                ),
                state,
                key=row.key,
            )
        self._inventory_content[table.id] = content
        return True

    async def _refresh_loop(self) -> None:
        while not self._closing:
            try:
                inventory = await self.engine.list_containers()
                self._update_launch_profiles(inventory)
                active = sum(item.state in ACTIVE_STATES for item in inventory)
                self.query_one("#docker-state", Static).update(
                    f"debugealo  ·  Docker: connected  ·  {active} active / {len(inventory)} total"
                )
                self._show_inventory(inventory)
            except DebugPilotError as error:
                self.query_one("#docker-state", Static).update(f"Docker unavailable: {error}")
                self._update_launch_profiles()
                self._show_inventory([])
            except Exception:
                self.query_one("#docker-state", Static).update(
                    "Docker unavailable: unable to read inventory. Retrying…"
                )
                self._update_launch_profiles()
                self._show_inventory([])
            await asyncio.sleep(self.refresh_interval)

    async def _stats_loop(self) -> None:
        """Sample one container's stats per interval; nothing is requested without a target."""
        while not self._closing:
            self._stats_wake.clear()
            target = self._stats_target
            if target is not None:
                try:
                    sample = await self.engine.container_stats(target)
                except (DebugPilotError, ValueError):
                    sample = None
                if target == self._stats_target and not self._closing:
                    cpu = cpu_percent(self._stats_previous, sample) if sample else None
                    self._stats_previous = sample
                    self.query_one(ContainerDetails).show_stats(cpu, sample)
            try:
                async with asyncio.timeout(self.refresh_interval):
                    await self._stats_wake.wait()
            except TimeoutError:
                pass

    def _set_stats_target(self, target: str | None) -> None:
        if target != self._stats_target:
            self._stats_target = target
            self._stats_previous = None
            self._stats_wake.set()

    @on(Checkbox.Changed, "#show-all")
    def visibility_changed(self, event: Checkbox.Changed) -> None:
        self._show_all = event.value
        self._show_inventory(list(self._inventory.values()), force=True)

    def _launch_profile_key(self, profile: LaunchProfile, index: int) -> str:
        if not profile.name or sum(p.name == profile.name for p in self._launch_profiles) > 1:
            # Array position is not identity: saving a reordered file must not
            # select the different Docker project now occupying the old slot.
            canonical = json.dumps(profile.raw, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            occurrence = sum(
                json.dumps(previous.raw, sort_keys=True, separators=(",", ":")) == canonical
                for previous in self._launch_profiles[:index]
            )
            return f"profile:{profile.name or 'unnamed'}:{digest}:{occurrence}"
        return f"profile:{profile.name}"

    def _render_launch_profiles(self) -> None:
        table = self.query_one("#launch-profiles", DataTable)
        rows: list[ContainerRow] = []
        self._launch_rows = {}
        self._launch_child_rows = {}
        for index, profile in enumerate(self._launch_profiles):
            key = self._launch_profile_key(profile, index)
            self._launch_rows[key] = profile
            members = sorted(
                (
                    item
                    for item in self._inventory.values()
                    if profile.project_name
                    and item.compose_project == profile.project_name
                    and (self._show_all or item.state in ACTIVE_STATES)
                ),
                key=lambda item: (item.compose_service or item.name).casefold(),
            )
            running = sum(item.state in ACTIVE_STATES for item in members)
            name = profile.name or f"Unnamed profile {index + 1}"
            rows.append(
                ContainerRow(
                    key=key,
                    label=f"{'▸' if key in self._collapsed_projects else '▾'} "
                    f"{name} · {profile.project_name or 'Needs setup'}",
                    # Non-numeric "…" marks a profile that still needs setup.
                    state="…" if profile.pending_reason else f"{running}/{len(members)}",
                    project=profile.project_name,
                )
            )
            for item in (() if key in self._collapsed_projects else members):
                child_key = f"profile-child:{key}:{item.id}"
                self._launch_child_rows[child_key] = (profile, item)
                rows.append(
                    ContainerRow(
                        key=child_key,
                        label=f"  {container_label(item)}",
                        state=item.state,
                        service=item.compose_service or "—",
                        container=item,
                        project=profile.project_name,
                    )
                )
        hidden = False
        for row in self._rows.values():
            if row.container is None:
                hidden = row.key in self._collapsed_projects
                rows.append(replace(row, label=row.label.replace("▾", "▸", 1)) if hidden else row)
            elif not hidden:
                rows.append(row)
        redrawn = self._render_inventory(table, rows)
        selected_row_key = self._selection_key or self._selected_profile_key
        if redrawn and selected_row_key in table.rows:
            table.move_cursor(row=table.get_row_index(selected_row_key))
        empty = self._launch_loaded and not rows and not self._launch_error
        self.query_one("#empty-welcome").display = empty
        table.display = not empty
        # Retain compatibility action widgets for integrations/tests, but the
        # primary keyboard-driven tree no longer shows duplicate action buttons.
        self.query_one("#profile-actions").display = False
        self.query_one("#launch-section").set_class(empty, "empty-launch")
        actionable = (
            self._selected_profile is not None
            and self._selected_profile.pending_reason is None
            and self._launch_error is None
        )
        self.query_one("#profile-recreate", Button).disabled = not actionable
        self.query_one("#profile-build-recreate", Button).disabled = not actionable

    def _update_launch_profiles(self, inventory: list[ContainerInfo] | None = None) -> None:
        if self._launch_store is None:
            self._launch_loaded = True
            self.query_one("#launch-state", Static).update(
                f"Launch profiles unavailable: {self._launch_error}"
            )
            self._launch_profiles = []
            self._selected_profile = None
            self._launch_rows = {}
            self._render_launch_profiles()
            return
        try:
            if inventory is not None:
                self._launch_store.register(inventory)
            profiles = [profile for profile in self._launch_store.profiles() if not profile.dynamic]
            self._launch_loaded = True
            previous_key = (
                self._selection_key
                if (self._selection_key or "").startswith("profile-child:")
                else self._selected_profile_key
            )
            table = self.query_one("#launch-profiles", DataTable)
            if previous_key is not None and table.row_count:
                cursor_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                if cursor_key in self._launch_rows:
                    previous_key = cursor_key
                    self._selected_profile_key = cursor_key
                elif cursor_key in self._launch_child_rows:
                    previous_key = cursor_key
                    owner, _item = self._launch_child_rows[cursor_key]
                    self._selected_profile_key = self._launch_profile_key(
                        owner, self._launch_profiles.index(owner)
                    )
            self._launch_profiles = profiles
            self._launch_error = None
            self._render_launch_profiles()
            pending = sum(profile.pending_reason is not None for profile in profiles)
            self.query_one("#launch-state", Static).update(
                f"Launch profiles: {len(profiles) - pending} ready / {pending} pending · "
                f"Ctrl+O · {self._launch_store.path}"
            )
            self.query_one("#launch-state").tooltip = str(self._launch_store.path)
            if self._pending_profile is not None:
                current = next(
                    (
                        profile
                        for index, profile in enumerate(profiles)
                        if self._launch_profile_key(profile, index) == self._pending_profile_key
                    ),
                    None,
                )
                if current is None or current.raw != self._pending_profile.raw:
                    self._dismiss_inline_compose()
                    self.notify(
                        "Launch profile changed after preview. Select it and preview again.",
                        severity="warning",
                    )
            if previous_key is not None:
                selected = self._launch_rows.get(previous_key)
                child = self._launch_child_rows.get(previous_key)
                if selected is not None:
                    self._select_launch_profile(previous_key, selected)
                elif child is not None:
                    self._select_launch_child(previous_key, *child)
                elif (self._selection_key or "").startswith(("profile:", "profile-child:")):
                    self._selected_profile = None
                    self._selected_profile_key = None
                    self._selected_profile_name = None
                    self._select(None)
            elif self._selection_key is None and profiles:
                first_key = self._launch_profile_key(profiles[0], 0)
                self._select_launch_profile(first_key, profiles[0])
            if self._inventory_loaded and inventory is None:
                self._show_inventory(list(self._inventory.values()))
        except (ConfigurationError, OSError) as error:
            self._launch_loaded = True
            self._launch_error = str(error)
            self._launch_profiles = []
            self._selected_profile = None
            self._selected_profile_key = None
            self._selected_profile_name = None
            if self._pending_profile is not None:
                self._dismiss_inline_compose()
            self.query_one("#launch-state", Static).update(
                f"Launch profiles: {error} · logs remain available"
            )
            self._render_launch_profiles()

    def _select_launch_profile(self, key: str, profile: LaunchProfile) -> None:
        if self._pending_profile is not None and key != self._pending_profile_key:
            self._dismiss_inline_compose()
            self.notify("Profile selection changed; preview the action again.", severity="warning")
        previous = (self._selection_key, self.selected_project)
        self._initial_inventory_selection_complete = True
        self._selected_profile = profile
        self._selected_profile_key = key
        self._selected_profile_name = profile.name
        if previous != (key, profile.project_name):
            self._selection_revision += 1
        self._select(None, project=profile.project_name, row_key=key)
        self.query_one("#profile-recreate", Button).disabled = bool(
            self._launch_error or profile.pending_reason
        )
        self.query_one("#profile-build-recreate", Button).disabled = bool(
            self._launch_error or profile.pending_reason
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
            service_overrides=resolved.service_overrides,
            services=resolved.services,
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
        ownership_signature = frozenset(
            profile.project_name for profile in self._launch_profiles if profile.project_name
        )
        if (
            self._inventory_loaded
            and current == self._inventory
            and ownership_signature == self._inventory_ownership_signature
            and not force
        ):
            return
        self._inventory_ownership_signature = ownership_signature
        focused_key = None
        if isinstance(self.focused, DataTable):
            if self.focused.id == "launch-profiles":
                # Layout refresh may run before the highlighted-row event is handled.
                if self.focused.row_count:
                    focused_key = self.focused.coordinate_to_cell_key(
                        self.focused.cursor_coordinate
                    ).row_key.value
                self._select_focused_row(self.focused)
        self._inventory_loaded = True
        previous_key, previous_project = self._selection_key, self.selected_project
        previous_container = self.selected_container
        self._inventory = current
        owned_projects = {
            profile.project_name for profile in self._launch_profiles if profile.project_name
        }
        unowned = [item for item in inventory if item.compose_project not in owned_projects]
        rows = [
            replace(row, key="stopped:" + row.key)
            if row.container is not None and row.container.state not in ACTIVE_STATES else row
            for row in container_rows([
                item for item in unowned if self._show_all or item.state in ACTIVE_STATES
            ])
        ]
        self._rows = {row.key: row for row in rows}
        self._render_launch_profiles()
        table = self.query_one("#launch-profiles", DataTable)
        all_rows = [row for row in rows if row.key in table.rows]
        self._rows = {row.key: row for row in all_rows}
        stopped_count = sum(item.state not in ACTIVE_STATES for item in inventory)
        self.query_one("#show-all", Checkbox).label = f"Show all ({stopped_count} stopped)"
        launch_child = self._launch_child_rows.get(previous_key or "")
        if launch_child is None and (previous_key or "").startswith("profile-child:"):
            owner_key = self._selected_profile_key
            candidates = [
                (key, profile, item)
                for key, (profile, item) in self._launch_child_rows.items()
                if self._launch_profile_key(profile, self._launch_profiles.index(profile))
                == owner_key
                and previous_container is not None
                and item.compose_service == previous_container.compose_service
            ]
            if previous_container is not None:
                exact_name = [
                    candidate
                    for candidate in candidates
                    if candidate[2].name == previous_container.name
                ]
                if exact_name:
                    candidates = exact_name
            if candidates:
                launch_child = candidates[0][1:]
                previous_key = candidates[0][0]
            elif owner_key in self._launch_rows:
                profile = self._launch_rows[owner_key]
                self._select_launch_profile(owner_key, profile)
                return
        if launch_child is not None:
            child_profile, child_item = launch_child
            launch_table = self.query_one("#launch-profiles", DataTable)
            launch_table.move_cursor(
                row=next(
                    index
                    for index, row in enumerate(launch_table.ordered_rows)
                    if row.key.value == previous_key
                )
            )
            self._select_launch_child(previous_key, child_profile, child_item)
            return
        profile = self._launch_rows.get(previous_key or "")
        if profile is not None:
            launch_table = self.query_one("#launch-profiles", DataTable)
            launch_table.move_cursor(
                row=next(
                    index
                    for index, row in enumerate(launch_table.ordered_rows)
                    if row.key.value == previous_key
                )
            )
            self._select_launch_profile(previous_key, profile)
            return
        selected = (
            self._rows.get(focused_key)
            if previous_key is not None or not self._initial_inventory_selection_complete
            else None
        ) or self._rows.get(previous_key)
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
        if selected is None and not self._initial_inventory_selection_complete:
            # Auto-select once only; a vanished selection must not jump to unrelated logs.
            selected = next((row for row in rows if row.container is not None), None)
        if selected is None and not self._initial_inventory_selection_complete:
            selected = next(iter(all_rows), None)
        if selected:
            table = self.query_one(
                "#launch-profiles",
                DataTable,
            )
            table.move_cursor(row=table.get_row_index(selected.key))
            self._initial_inventory_selection_complete = True
            self._select(selected.container, project=selected.project, row_key=selected.key)
        else:
            self._select(None)

    @on(DataTable.RowHighlighted, "#launch-profiles")
    def launch_profile_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._select_focused_row(event.data_table, expected_key=event.row_key.value)

    @on(DataTable.RowSelected, "#launch-profiles")
    def launch_profile_selected(self, event: DataTable.RowSelected) -> None:
        self._select_focused_row(event.data_table, expected_key=event.row_key.value)

    @on(events.DescendantFocus, "#launch-profiles")
    def launch_profile_focused(self, event: events.DescendantFocus) -> None:
        self._select_focused_row(event.widget)

    def _select_focused_row(self, table: DataTable, *, expected_key: str | None = None) -> None:
        if table.row_count and table.has_focus and table.is_mounted and not self._closing:
            # Rebuilding inventory can enqueue old highlight events; accept only
            # the row that is still under the cursor, not an obsolete selection.
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            if expected_key is None or expected_key == key:
                row = self._rows.get(key)
                if table.id == "launch-profiles":
                    profile = self._launch_rows.get(key)
                    child = self._launch_child_rows.get(key)
                    if profile is not None:
                        self._select_launch_profile(key, profile)
                    elif child is not None:
                        self._select_launch_child(key, *child)
                    if profile is not None or child is not None:
                        return
                if row is not None:
                    if self._pending_profile is not None and key != self._pending_profile_key:
                        self._dismiss_inline_compose()
                        self.notify(
                            "Profile selection changed; preview the action again.",
                            severity="warning",
                        )
                    if row.key != self._selection_key:
                        self._selection_revision += 1
                    self._initial_inventory_selection_complete = True
                    self._selected_profile = None
                    self._selected_profile_key = None
                    self._selected_profile_name = None
                    table.tooltip = Text(
                        f"{row.container.name if row.container else row.label.strip()}\n"
                        f"State: {row.state if row.container else row.state + ' running'}\n"
                        f"Service: {row.service or '—'}"
                    )
                    self._select(row.container, project=row.project, row_key=row.key)

    def _select_launch_child(self, key: str, profile: LaunchProfile, item: ContainerInfo) -> None:
        profile_key = self._launch_profile_key(profile, self._launch_profiles.index(profile))
        if self._pending_profile is not None and self._pending_profile_key != profile_key:
            self._dismiss_inline_compose()
            self.notify("Profile selection changed; preview the action again.", severity="warning")
        self._selected_profile = profile
        self._selected_profile_key = self._launch_profile_key(
            profile, self._launch_profiles.index(profile)
        )
        self._selected_profile_name = profile.name
        table = self.query_one("#launch-profiles", DataTable)
        if key in self._launch_child_rows:
            table.move_cursor(
                row=next(
                    index for index, row in enumerate(table.ordered_rows) if row.key.value == key
                ),
                scroll=False,
            )
        if key != self._selection_key:
            self._selection_revision += 1
        self._select(item, project=profile.project_name, row_key=key)

    def _select(
        self,
        item: ContainerInfo | None,
        *,
        project: str | None = None,
        row_key: str | None = None,
        force: bool = False,
    ) -> None:
        old = (
            _selection_signature(self.selected_container),
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
                "Ctrl+L shows combined project logs; select a service for details."
            )
        elif self._selection_key == "standalone:":
            empty_detail = (
                "Standalone containers have no Compose project. Select a container for details."
            )
        self.query_one("#container-info", Static).update(
            Text(
                f"{item.image}\n{item.id[:12]} · {item.state}\n"
                f"Compose: {item.compose_project or '—'} / {item.compose_service or '—'}"
            )
            if item
            else Text(empty_detail)
        )
        if (old[1], old[2]) != (self.selected_project, self._selection_key):
            self._logs_requested = False
        if force or old != (
            _selection_signature(item),
            self.selected_project,
            self._selection_key,
            self._group_signature,
        ):
            self._generation += 1
            self._selection_changed.set()
        self._show_selection_panel()

    def _show_selection_panel(self) -> None:
        """Show container details by default and the log panel only on request."""
        if self.query_one("#container-shell").display:
            self._set_stats_target(None)
            return
        item = self.selected_container
        details = self.query_one(ContainerDetails)
        overview = self.query_one(ProjectOverview)
        # The overview lists every project container, stopped ones included.
        members = (
            tuple(
                value
                for value in self._inventory.values()
                if value.compose_project == self.selected_project
            )
            if item is None and self.selected_project
            else ()
        )
        show_details = item is not None and not self._logs_requested
        show_overview = bool(members) and not self._logs_requested
        self._set_stats_target(
            item.id if show_details and item.state == "running" else None
        )
        if show_details:
            details.show_container(item)
        if show_overview:
            overview.show_project(self.selected_project or "", members)
        details.display = show_details
        overview.display = show_overview
        self.query_one("#logs-panel").display = not (show_details or show_overview)

    def _set_logs_requested(self, requested: bool) -> None:
        self._logs_requested = requested
        self._generation += 1
        self._selection_changed.set()
        self._show_selection_panel()

    def _compose_output_matches_selection(self, project: str | None) -> bool:
        """Any row of a Compose project (project, profile or container) shows its output."""
        return project is not None and project == self.selected_project

    def _restore_compose_output(self, viewer: LogViewer | None = None) -> None:
        console = self.query_one(ExecutionConsole)
        console.clear()
        buffer = self._compose_outputs.get(self.selected_project)
        if buffer is not None:
            self._compose_outputs.touch(self.selected_project)
            for entry in buffer.entries():
                console.append(entry)
        for entry in self._stop_output:
            console.append(entry)

    def _begin_compose_output(self, run: _ComposeRun) -> None:
        # A new run clears only its own project's transcript.
        self._compose_outputs.reset(run.project)
        if self._compose_output_matches_selection(run.project) and not self._closing:
            self._restore_compose_output()
        self._record_compose_output(
            run, f"Starting {run.plan.action}: {run.project} / {_plan_scope(run.plan)}"
        )

    def _record_compose_output(
        self, run: _ComposeRun, text: str, *, severity: str = "unknown"
    ) -> None:
        if not text:
            return
        prefix = f"[Compose · {(run.prefix or 'profile')[:256]}] "
        combined = prefix + text
        truncated = len(combined) > 16_384
        entry = LogEntry(
            stream="combined",
            text=combined[:16_384],
            severity=severity,
            truncated=truncated,
        )
        self._compose_outputs.append(run.project, entry)
        if self._compose_output_matches_selection(run.project) and not self._closing:
            self.query_one(ExecutionConsole).append(entry)

    def _write_compose_output(self, run: _ComposeRun, text: str) -> None:
        for line in text.splitlines():
            self._record_compose_output(run, line)

    def _limit_to_profile_services(self, members):
        """Keep only the selected profile's explicit services, when it declares any."""
        profile = self._selected_profile
        if profile is None or profile.project_name != self.selected_project:
            return members
        services = profile_services(profile.raw)
        if not services:
            return members
        return [item for item in members if item.compose_service in services]

    def _group_members(self) -> tuple[ContainerInfo, ...]:
        if self.selected_container is not None or not self.selected_project:
            return ()
        stopped = (self._selection_key or "").startswith("stopped:")
        return tuple(
            item
            for item in self._inventory.values()
            if item.compose_project == self.selected_project
            and (item.state not in ACTIVE_STATES) == stopped
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
                viewer = self.query_one(LogViewer)
                viewer.action_clear_logs()
                self._restore_compose_output()
                members = self._group_members()
                if not self._logs_requested:
                    if item is None and members:
                        self.query_one("#log-state", Static).update(
                            f"Project · {self.selected_project} · {len(members)} services"
                            " · Ctrl+L shows logs"
                        )
                    elif item is None:
                        self.query_one("#log-state", Static).update(
                            self._no_container_message()
                        )
                    continue
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
                    self.query_one("#log-state", Static).update(self._no_container_message())
                else:
                    self.query_one("#log-state", Static).update(f"Logs · {item.name}")
                    self._stream_task = asyncio.create_task(self._consume(item, generation))
        finally:
            await self._stop_stream()

    def _no_container_message(self) -> str:
        return (
            f"Project · {self.selected_project} · select a service for logs"
            if self.selected_project
            else "No active containers; enable Show all"
            if self._inventory and not self._show_all
            else "No container selected"
        )

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
        operations = [
            task
            for task in (self._credential_task, *self._compose_tasks.values())
            if task is not None
        ]
        for task in operations:
            task.cancel()
        if operations:
            await asyncio.gather(*operations, return_exceptions=True)
        if self._launch_open_task is not None:
            self._launch_open_task.cancel()
            await asyncio.gather(self._launch_open_task, return_exceptions=True)
        await self._cancel_terminal_open()
        await self._close_terminal_views()
        self._selection_changed.set()
        if self._stats_task is not None:
            self._stats_task.cancel()
            await asyncio.gather(self._stats_task, return_exceptions=True)
        if self._update_task is not None:
            self._update_task.cancel()
            await asyncio.gather(self._update_task, return_exceptions=True)
        # Let the selection owner finish any pending stream cleanup rather than
        # cancelling it a second time in the middle of an async generator finally.
        if self._ui_tasks:
            self._ui_tasks[0].cancel()
            await asyncio.gather(*self._ui_tasks, return_exceptions=True)
        await self.engine.close()

    def action_container_pane(self, step: int) -> None:
        """Move between the list and the focusable view on the right, wrapping around."""
        panes = [self.query_one("#launch-profiles", DataTable)]
        if self.query_one("#logs-panel").display:
            panes.append(self.query_one("#log-entries", DataTable))
        elif self.query_one(ProjectOverview).display:
            panes.append(self.query_one("#project-overview-table", DataTable))
        focused = self.focused
        current = next((index for index, pane in enumerate(panes)
                        if focused is pane or (focused is not None and pane in focused.ancestors)),
                       None)
        if current is None and focused is not None and any(
            container in focused.ancestors
            for container in (self.query_one("#logs-panel"), self.query_one(ProjectOverview))
        ):
            current = len(panes) - 1
        if current is None:
            panes[0].focus()
            return
        panes[(current + step) % len(panes)].focus()

    @on(Button.Pressed, "#container-shell-logs")
    def action_focus_logs(self) -> None:
        if self.query_one("#container-shell").display:
            self.query_one("#container-shell").display = False
        if not self._logs_requested:
            self._set_logs_requested(True)
        else:
            self._show_selection_panel()
        self.query_one("#log-entries", DataTable).focus()

    def _show_container_terminal(self, visible: bool) -> None:
        self.query_one("#container-shell").display = visible
        if visible:
            self.query_one("#logs-panel").display = False
            self.query_one(ContainerDetails).display = False
            self.query_one(ProjectOverview).display = False
        else:
            self._show_selection_panel()

    def action_show_container_details(self) -> None:
        if self.selected_container is None:
            self.notify("Select a container to view its details.", severity="warning")
            return
        self.query_one("#container-shell").display = False
        if self._logs_requested:
            self._set_logs_requested(False)
        else:
            self._show_selection_panel()

    def action_toggle_compose_output(self) -> None:
        self._compose_output_visible = not self._compose_output_visible
        self.query_one(ExecutionConsole).set_output_visible(self._compose_output_visible)
        if not self._compose_output_visible:
            self._focus_terminal_selection()

    async def action_toggle_host_terminal(self) -> None:
        """Open the host shell, or collapse/restore it while keeping the session."""
        host = self.query_one(HostTerminal)
        if self._host_terminal_pane is None:
            return
        if not self._host_terminal_pane.active:
            await self.action_open_host_terminal()
            return
        minimized = not host.has_class("minimized")
        host.set_class(minimized, "minimized")
        host.display = True
        if minimized:
            self._focus_terminal_selection()
        else:
            self.call_after_refresh(self._host_terminal_pane.focus)

    def _left_table_focused(self) -> bool:
        return (
            isinstance(self.focused, DataTable)
            and self.focused.id == "launch-profiles"
        )

    def action_toggle_project(self) -> None:
        if not self._left_table_focused():
            return
        self._select_focused_row(self.focused)
        key = self._selection_key
        row = self._rows.get(key)
        if key not in self._launch_rows and (row is None or row.container is not None):
            return
        self._collapsed_projects.symmetric_difference_update({key})
        self._show_inventory(list(self._inventory.values()), force=True)

    def _focus_terminal_selection(self) -> None:
        self.query_one(self._selection_table_selector(), DataTable).focus()

    async def action_open_container_terminal(self) -> None:
        if not self._left_table_focused():
            return
        selected = self.selected_container
        if selected is None:
            self._terminal_status("Select a running container row before opening its shell.")
            return
        current = self._inventory.get(selected.id)
        if current is None or current.state.lower() != "running":
            self._terminal_status("The selected container is not running; select a running row.")
            return
        if self._terminal_open_task is not None and not self._terminal_open_task.done():
            return
        target = current
        workspace = self._terminal_workspace()
        if workspace is None:
            return
        endpoint = self.engine.settings.docker_endpoint or default_endpoint()
        await self._open_terminal("container", target=target, endpoint=endpoint, cwd=workspace)

    async def action_open_host_terminal(self) -> None:
        if not self._left_table_focused():
            return
        if self._terminal_open_task is not None and not self._terminal_open_task.done():
            return
        workspace = self._terminal_workspace()
        if workspace is None:
            return
        await self._open_terminal("host", cwd=workspace)

    def _terminal_workspace(self) -> Path | None:
        store = self._launch_store
        workspace = store.workspace if store is not None else None
        if workspace is None and store is not None and self._selected_profile is not None:
            resolved = store.resolve(self._selected_profile)
            if resolved is not None:
                workspace = resolved.cwd
        if workspace is None or not workspace.is_dir():
            message = self._launch_error or "Select a usable workspace before opening a terminal."
            self._terminal_status(f"Terminal unavailable: {message}")
            return None
        return workspace

    def _terminal_status(self, message: str) -> None:
        if self._terminal_pane is self._container_terminal_pane:
            self.query_one("#container-terminal-context", Static).update(message)
        else:
            self.query_one(HostTerminal).set_terminal_status(message)

    async def _open_terminal(
        self,
        kind: str,
        *,
        cwd: Path,
        target: ContainerInfo | None = None,
        endpoint: str | None = None,
    ) -> None:
        pane = self._container_terminal_pane if kind == "container" else self._host_terminal_pane
        if pane is None or self._closing:
            return
        previous = self._terminal_pane
        self._terminal_pane = pane
        if kind == "container":
            self._show_container_terminal(True)
        else:
            if self.query_one("#container-shell").display:
                self._show_container_terminal(False)
            host = self.query_one(HostTerminal)
            host.remove_class("minimized")
            host.display = True
        context_label = (
            f"Container · {target.name} · {target.id[:12]} · {endpoint} · {cwd}"
            if kind == "container" and target is not None
            else f"Host Bash · {cwd}"
        )
        context = pane.context
        if (kind == "container" and pane.active and context is not None
                and context.container is not None and context.container.id == target.id
                and context.endpoint == endpoint and context.cwd == cwd):
            self._terminal_status(f"{context_label} · Esc returns to left table")
            self.call_after_refresh(pane.focus)
            return
        self._terminal_status(f"Opening {context_label}")

        async def open_session() -> None:
            try:
                if previous is not None:
                    closing = asyncio.create_task(previous.close_session())
                    try:
                        await asyncio.shield(closing)
                    except asyncio.CancelledError:
                        await closing
                        raise
                if kind == "container":
                    host = self.query_one(HostTerminal)
                    host.set_terminal_status("Host terminal inactive · H host Bash")
                    host.display = False
                if kind == "container":
                    await pane.open_container(target, endpoint, cwd)
                else:
                    await pane.open_host(cwd)
                if not self._closing:
                    self._terminal_status(f"{context_label} · Esc returns to left table")
                    self.call_after_refresh(pane.focus)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not self._closing:
                    self._terminal_status(
                        f"Terminal unavailable: {error}. Check Bash/Docker and the "
                        "selected context."
                    )
            finally:
                if self._terminal_open_task is asyncio.current_task():
                    self._terminal_open_task = None

        self._terminal_open_task = asyncio.create_task(open_session())

    async def _cancel_terminal_open(self) -> None:
        task = self._terminal_open_task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self._terminal_open_task is task:
                self._terminal_open_task = None

    async def _close_terminal_views(self) -> None:
        for pane in (self._host_terminal_pane, self._container_terminal_pane):
            if pane is not None:
                await pane.close_session()

    async def action_close_terminal(self) -> None:
        await self._cancel_terminal_open()
        await self._close_terminal_views()
        if self._terminal_pane is self._container_terminal_pane:
            self._show_container_terminal(False)
        else:
            host = self.query_one(HostTerminal)
            host.remove_class("minimized")
            host.display = False
            self._focus_terminal_selection()
        self._terminal_status("Terminal closed · C container shell · H host Bash")

    def action_retry_logs(self) -> None:
        if self.selected_container or self.selected_project:
            self._select(
                self.selected_container,
                project=self.selected_project,
                row_key=self._selection_key,
                force=True,
            )

    def action_run_code(self) -> None:
        workspace = self.query_one(CodeWorkspace)
        if workspace.display:
            workspace.run_selected()
        else:
            self.action_debugger_unavailable()

    def action_debug_code(self) -> None:
        self.query_one(CodeWorkspace).debug_selected()

    def action_toggle_code_terminal(self) -> None:
        self.query_one(CodeWorkspace).toggle_terminal()

    def action_code_step_over(self) -> None:
        self.query_one(CodeWorkspace).debug_control("step_over")

    def action_code_step_in(self) -> None:
        self.query_one(CodeWorkspace).debug_control("step_in")

    def action_code_step_out(self) -> None:
        self.query_one(CodeWorkspace).debug_control("step_out")

    def action_debugger_unavailable(self) -> None:
        self.notify("Debugger controls are available in the Code area.")

    def action_toggle_breakpoint(self) -> None:
        workspace = self.query_one(CodeWorkspace)
        if workspace.display:
            workspace.toggle_breakpoint()
        else:
            self.action_debugger_unavailable()

    def action_edit_breakpoint(self) -> None:
        workspace = self.query_one(CodeWorkspace)
        if workspace.display:
            workspace.edit_breakpoint()
        else:
            self.action_debugger_unavailable()

    def action_compose(self) -> None:
        self.action_open_launch_file()

    def copy_to_clipboard(self, text: str) -> None:
        """OSC 52 for terminals that support it, plus the local OS clipboard.

        Some terminals (macOS Terminal, Warp) ignore OSC 52, which made Ctrl+C on
        a mouse selection appear to do nothing.
        """
        super().copy_to_clipboard(text)
        from debugpilot.tui.clipboard import copy_native

        copy_native(text)

    def on_text_selected(self, event: events.TextSelected) -> None:
        """Copy on select: releasing the mouse after a drag copies what it covered."""
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)
            noun = "character" if len(text) == 1 else "characters"
            self.notify(f"Copied {len(text)} {noun}", timeout=2)

    @on(Button.Pressed, "#open-launch-file")
    @on(Button.Pressed, "#welcome-open-launch")
    def action_open_launch_file(self) -> None:
        self._open_area_launch(code=self.query_one(CodeWorkspace).display)

    def _open_area_launch(self, *, code: bool) -> None:
        store = self.query_one(CodeWorkspace).store if code else self._launch_store
        if store is None:
            self.notify(
                f"Launch profiles unavailable: {self._launch_error or 'workspace is unavailable.'}",
                severity="warning",
            )
            return
        if self._launch_open_task is not None and not self._launch_open_task.done():
            return

        async def open_file() -> None:
            try:
                from debugpilot.tui.launch_file import open_launch_file

                path = await asyncio.to_thread(store.ensure_launch_file)
                self._edit_launch_in_terminal(open_launch_file, path)
                if not self._closing:
                    if code:
                        self.query_one(CodeWorkspace).reload_profiles()
                    else:
                        self._update_launch_profiles()
                    self.notify(f"Returned from editor: {path}")
            except (ConfigurationError, OSError) as error:
                if not self._closing:
                    self.notify(f"Cannot open launch.json: {error}", severity="warning")
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self._closing:
                    self.notify("Cannot open launch.json in an editor.", severity="warning")
            finally:
                self._launch_open_task = None

        self._launch_open_task = asyncio.create_task(open_file())
        self._ui_tasks.append(self._launch_open_task)
        self._launch_open_task.add_done_callback(
            lambda task: self._ui_tasks.remove(task) if task in self._ui_tasks else None
        )

    def _edit_launch_in_terminal(self, editor, path: Path) -> None:
        # Keep terminal ownership on the UI thread. Async refreshes must not
        # compete with the editor. Textual's suspend() has no try/finally around
        # its yield, so an exception escaping the block would skip
        # resume_application_mode() and leave the dashboard frozen; hold it until
        # the UI is restored, then re-raise so the caller can report it.
        failure: BaseException | None = None
        with self.suspend():
            try:
                editor(path)
            except BaseException as error:  # noqa: BLE001 - re-raised after resume
                failure = error
        if failure is not None:
            raise failure

    def _remember_compose_project(self, project: ComposeProject) -> None:
        self._compose_projects[project.project_name] = project
        try:
            self._compose_store.save(project)
        except ConfigurationError as error:
            self.notify(
                f"Compose succeeded, but routes were not saved: {error}", severity="warning"
            )

    def action_recreate_selected(self) -> None:
        self._launch_profile_action("recreate")

    @on(Button.Pressed, "#profile-recreate")
    def action_profile_recreate(self) -> None:
        self._launch_profile_action("recreate")

    def action_build_selected(self) -> None:
        self._launch_profile_action("rebuild")

    @on(Button.Pressed, "#profile-build-recreate")
    def action_profile_build_recreate(self) -> None:
        self._launch_profile_action("rebuild")

    def _launch_profile_action(self, action: str) -> None:
        from debugpilot.docker.compose import ComposeService

        profile = self._selected_profile
        if profile is None:
            self.notify("Select a saved launch profile before running Compose.", severity="warning")
            return
        if profile.pending_reason is not None:
            self.notify(
                f"Launch profile pending: {profile.pending_reason}. Edit launch.json first.",
                severity="warning",
            )
            return
        if self._credential_busy():
            self.notify("An operation is already running.", severity="warning")
            return
        if self._refuse_busy_bar():
            return
        if self._project_is_composing(profile.project_name):
            # Only the busy project is blocked; other projects can run at the same time.
            self.notify(
                f"A Compose operation is already running for {profile.project_name}.",
                severity="warning",
            )
            return
        if self._project_is_stopping(profile.project_name):
            # Only the project being stopped is off-limits; other projects stay usable.
            self.notify(
                f"{profile.project_name} is stopping; wait for it to finish.", severity="warning"
            )
            return
        if self._launch_error or self._launch_store is None:
            self.notify(
                "Fix launch profiles before running Compose: "
                f"{self._launch_error or 'unavailable'}",
                severity="warning",
            )
            return
        try:
            project = self._project_from_profile(profile)
            service = ComposeService(self.engine.settings)
            plan = service.preview(project, action)
        except (ConfigurationError, ComposeError) as error:
            self.notify(f"Launch profile pending: {error}. Edit launch.json.", severity="warning")
            return
        self._dismiss_inline_compose()
        self._inline_plan = plan
        self._inline_service = service
        self._pending_profile = profile
        self._pending_profile_key = self._selected_profile_key
        verb = "Recreate" if action == "recreate" else "Build and recreate"
        self.query_one("#inline-compose-message", Static).update(
            f"{verb} {profile.name or project.project_name} / {_plan_scope(plan)}?"
        )
        self.query_one("#inline-compose").tooltip = plan.display
        self.query_one("#inline-compose").display = True
        self.query_one("#inline-compose-confirm", Button).disabled = False
        self.query_one("#inline-compose-cancel", Button).label = "Cancel"
        self.query_one("#inline-compose-confirm", Button).focus()

    def _open_compose(self, initial_action: str = "recreate", *, contextual: bool = False) -> None:
        from debugpilot.docker.compose import ComposeService
        from debugpilot.tui.compose_dialog import ComposeDialog

        if self._credential_busy():
            self.notify("An operation is already running.", severity="warning")
            return
        if self._refuse_busy_bar():
            return
        # Resolve the visibly focused cursor even if a focus event is still queued.
        if isinstance(self.focused, DataTable) and self.focused.id == "launch-profiles":
            self._select_focused_row(self.focused)
        if self._project_is_composing(self.selected_project):
            self.notify(
                f"A Compose operation is already running for {self.selected_project}.",
                severity="warning",
            )
            return
        if self._project_is_stopping(self.selected_project):
            self.notify(
                f"{self.selected_project} is stopping; wait for it to finish.", severity="warning"
            )
            return
        self._dismiss_inline_compose()

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
        if self._retry_decision is not None and not self._retry_decision.done():
            self._retry_decision.set_result(False)
        self._retry_decision = None
        self._pending_retry_plan = None
        self._pending_retry_fingerprint = None
        self._inline_plan = None
        self._pending_stop = ()
        self._pending_credential_recreates = []
        self._pending_profile = None
        self._pending_profile_key = None
        self.query_one("#inline-compose-confirm", Button).label = "Confirm"
        self.query_one("#inline-compose-confirm", Button).disabled = False
        self.query_one("#inline-compose-cancel", Button).label = "Cancel"
        self.query_one("#inline-compose-cancel", Button).disabled = False
        self.query_one("#inline-compose").display = False
        # Wake a mid-run consent waiting for the bar.
        self._bar_idle.set()

    @on(Button.Pressed, "#compose-output-toggle")
    def toggle_compose_output_button(self) -> None:
        self.action_toggle_compose_output()

    @on(Button.Pressed, "#stop-selected")
    def action_stop_selected(self) -> None:
        if self._credential_busy():
            self.notify("An operation is already running.", severity="warning")
            return
        if self._refuse_busy_bar():
            return
        if isinstance(self.focused, DataTable) and self.focused.id == "launch-profiles":
            self._select_focused_row(self.focused)
        members = (
            [self.selected_container]
            if self.selected_container is not None
            else list(self._group_members())
            if self.selected_project
            else []
        )
        if self.selected_container is None:
            members = self._limit_to_profile_services(members)
        targets = tuple(c.id for c in members if c.state in ACTIVE_STATES)
        composing = next(
            (
                c.compose_project
                for c in members
                if c.id in targets and self._project_is_composing(c.compose_project)
            ),
            None,
        )
        if composing is not None:
            # Mirrors the stop rule: a project being recreated cannot be stopped meanwhile.
            self.notify(
                f"{composing} is being recreated; wait for it to finish.", severity="warning"
            )
            return
        if targets and all(target in self._stopping for target in targets):
            self.notify("Already stopping; see the output.", severity="warning")
            return
        targets = tuple(target for target in targets if target not in self._stopping)
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
        if (
            self._pending_credential_recreates
            and not self._credential_busy()
            and not self._compose_running()
        ):
            batch, self._pending_credential_recreates = self._pending_credential_recreates, []
            if not self._credential_batch_is_current(batch):
                self._dismiss_inline_compose()
                self.notify(
                    "Launch profiles changed after the credential refresh. Recreate manually.",
                    severity="warning",
                )
                return
            self.query_one("#inline-compose-confirm", Button).disabled = True
            self.query_one("#inline-compose-cancel", Button).label = "Stop CLI"
            self._credential_task = asyncio.create_task(self._run_credential_recreates(batch))
            return
        if self._pending_stop and not self._credential_busy():
            targets, self._pending_stop = self._pending_stop, ()
            # Free the bar right away so another stop can be confirmed while Docker
            # works; progress goes to the output card.
            self._dismiss_inline_compose()
            self.query_one(self._selection_table_selector(), DataTable).focus()
            self._stopping.update(targets)
            task = asyncio.create_task(self._run_stop(targets))
            self._stop_tasks.add(task)
            task.add_done_callback(self._stop_tasks.discard)
            return
        if self._retry_decision is not None and not self._retry_decision.done():
            self.query_one("#inline-compose-confirm", Button).disabled = True
            self.query_one("#inline-compose-cancel", Button).disabled = True
            self._retry_decision.set_result(True)
            return
        if self._inline_plan is None or self._credential_busy():
            return
        if self._pending_profile is not None:
            try:
                current_profile = next(
                    (
                        profile
                        for index, profile in enumerate(self._launch_store.profiles())
                        if not profile.dynamic
                        and self._launch_profile_key(profile, index) == self._pending_profile_key
                    ),
                    None,
                )
                unchanged = (
                    current_profile is not None
                    and current_profile.raw == self._pending_profile.raw
                    and self._project_from_profile(current_profile) == self._inline_plan.project
                )
            except (ConfigurationError, ComposeError, OSError):
                unchanged = False
            if not unchanged:
                self._dismiss_inline_compose()
                self.notify(
                    "Launch profile changed after preview. Select it and preview again.",
                    severity="warning",
                )
                return
        plan = self._inline_plan
        if self._project_is_composing(plan.project.project_name):
            self._dismiss_inline_compose()
            self.notify(
                f"A Compose operation is already running for {plan.project.project_name}.",
                severity="warning",
            )
            return
        run = self._new_compose_run(
            plan, self._inline_service, self._pending_profile, self._pending_profile_key
        )
        # Free the bar right away so other projects can be previewed and confirmed while
        # this run continues; progress goes to the project's output and toasts.
        self._dismiss_inline_compose()
        self.query_one(self._selection_table_selector(), DataTable).focus()
        self._start_compose_run(run)

    def _new_compose_run(
        self,
        plan: ComposePlan,
        service,
        profile: LaunchProfile | None,
        profile_key: str | None,
    ) -> _ComposeRun:
        return _ComposeRun(
            plan=plan,
            service=service,
            profile=profile,
            profile_key=profile_key,
            prefix=(profile.name if profile else None) or plan.project.project_name,
            selection=self.selected_container,
            selected_project=self.selected_project,
            revision=self._selection_revision,
        )

    def _start_compose_run(self, run: _ComposeRun) -> None:
        # Forget finished runs whose output was already evicted.
        retained = set(self._compose_outputs.projects())
        self._compose_tasks = {
            project: task
            for project, task in self._compose_tasks.items()
            if not task.done() or project in retained
        }
        self._compose_tasks[run.project] = asyncio.create_task(self._run_inline_compose(run))

    def action_refresh_aws_credentials(self) -> None:
        if self._credential_busy() or self._compose_running():
            self.notify("An operation is already running.", severity="warning")
            return
        if self._launch_store is None or self._launch_error:
            self.notify(
                f"Fix launch profiles first: {self._launch_error or 'unavailable'}",
                severity="warning",
            )
            return
        try:
            targets = self._launch_store.aws_credential_targets()
        except (ConfigurationError, OSError) as error:
            self.notify(f"Cannot read launch profiles: {error}", severity="warning")
            return
        if not targets:
            self.notify(
                "No launch profile declares awsCredentials. Add it in launch.json.",
                severity="warning",
            )
            return
        self._dismiss_inline_compose()
        self.query_one("#inline-compose-message", Static).update(
            f"Refreshing AWS credentials for {len(targets)} profile(s)…"
        )
        self.query_one("#inline-compose").tooltip = None
        self.query_one("#inline-compose").display = True
        self.query_one("#inline-compose-confirm", Button).disabled = True
        self._credential_task = asyncio.create_task(self._run_credential_refresh(targets))

    async def _run_credential_refresh(self, targets) -> None:
        from debugpilot.storage.aws_credentials import refresh_targets

        named = [(profile.name or profile.project_name or "profile", t) for profile, t in targets]
        result = await asyncio.to_thread(refresh_targets, named)
        if self._closing:
            return
        for error in result.errors:
            self.notify(error[:500], severity="error", timeout=15)
        if not result.profiles:
            self._dismiss_inline_compose()
            return
        updated = {name for name in result.profiles}
        batch = self._credential_recreate_batch(
            [profile for profile, _target in targets if
             (profile.name or profile.project_name or "profile") in updated]
        )
        expiry = "; ".join(f"{k} until {v}" for k, v in result.expirations.items())
        summary = f"AWS credentials updated in {len(result.updated_files)} file(s)" + (
            f" ({expiry})" if expiry else ""
        )
        if not batch:
            self._dismiss_inline_compose()
            self.notify(summary + ". No affected profile is running.", severity="information")
            return
        self._pending_credential_recreates = batch
        names = ", ".join(name for name, _key, _plan, _service, _raw in batch)
        self.query_one("#inline-compose-message", Static).update(
            f"{summary}. Recreate {names} to apply them?"
        )
        self.query_one("#inline-compose").tooltip = "\n".join(
            plan.display for _name, _key, plan, _service, _raw in batch
        )
        self.query_one("#inline-compose-confirm", Button).disabled = False
        self.query_one("#inline-compose-cancel", Button).label = "Skip"
        self.query_one("#inline-compose-confirm", Button).focus()

    def _credential_recreate_batch(self, profiles) -> list:
        """Recreate plans for refreshed profiles whose project has active containers."""
        from debugpilot.docker.compose import ComposeService

        active = {
            item.compose_project
            for item in self._inventory.values()
            if item.state in ACTIVE_STATES and item.compose_project
        }
        batch = []
        for profile in profiles:
            if profile.project_name not in active or profile.pending_reason:
                continue
            index = next(
                (
                    i
                    for i, current in enumerate(self._launch_profiles)
                    if not current.dynamic and current.raw == profile.raw
                ),
                None,
            )
            if index is None:
                continue
            try:
                service = ComposeService(self.engine.settings)
                plan = service.preview(self._project_from_profile(profile), "recreate")
            except (ConfigurationError, ComposeError):
                continue
            batch.append(
                (
                    profile.name or profile.project_name,
                    self._launch_profile_key(self._launch_profiles[index], index),
                    plan,
                    service,
                    profile,
                )
            )
        return batch

    def _credential_batch_is_current(self, batch) -> bool:
        try:
            current = [p for p in self._launch_store.profiles() if not p.dynamic]
            for _name, _key, plan, _service, profile in batch:
                match = next((p for p in current if p.raw == profile.raw), None)
                if match is None or self._project_from_profile(match) != plan.project:
                    return False
        except (ConfigurationError, ComposeError, OSError):
            return False
        return True

    async def _run_credential_recreates(self, batch) -> None:
        try:
            for _name, key, plan, service, profile in batch:
                run = self._new_compose_run(plan, service, profile, key)
                # The exclusive batch keeps the bar as its progress line.
                self.query_one("#inline-compose-message", Static).update(
                    f"Running recreate: {plan.project.project_name} / {_plan_scope(plan)}"
                )
                self.query_one("#inline-compose-confirm", Button).disabled = True
                self.query_one("#inline-compose-cancel", Button).label = "Stop CLI"
                self.query_one("#inline-compose").display = True
                await self._run_inline_compose(run)
        finally:
            if not self._closing:
                self._dismiss_inline_compose()
                self.query_one(self._selection_table_selector(), DataTable).focus()

    def _selection_table_selector(self) -> str:
        return "#launch-profiles"

    def _project_is_composing(self, project: str | None) -> bool:
        """Whether this Compose project has a Recreate / Build+Recreate run in flight."""
        task = self._compose_tasks.get(project) if project else None
        return task is not None and not task.done()

    def _compose_running(self) -> bool:
        return any(not task.done() for task in self._compose_tasks.values())

    def _credential_busy(self) -> bool:
        return self._credential_task is not None and not self._credential_task.done()

    def _consent_pending(self) -> bool:
        return self._retry_decision is not None and not self._retry_decision.done()

    def _bar_has_pending(self) -> bool:
        """Whether the inline bar holds a preview awaiting the user's decision."""
        return (
            self._inline_plan is not None
            or bool(self._pending_stop)
            or bool(self._pending_credential_recreates)
        )

    def _refuse_busy_bar(self) -> bool:
        """A pending download consent owns the bar; new previews must not replace it."""
        if self._consent_pending():
            self.notify("Answer the pending download prompt first.", severity="warning")
            return True
        return False

    def _project_is_stopping(self, project: str | None) -> bool:
        """Whether any container of this Compose project has a stop in flight."""
        return bool(project) and any(
            item.compose_project == project
            for target in self._stopping
            if (item := self._inventory.get(target)) is not None
        )

    def _report_stop(self, text: str, *, severity: str = "info") -> None:
        """Write a stop step into the output card, which Compose otherwise owns."""
        if not self._closing:
            if not self._compose_output_visible:
                self._compose_output_visible = True
                self.query_one(ExecutionConsole).set_output_visible(True)
            entry = LogEntry(stream="combined", text=f"[Stop] {text}"[:16_384], severity=severity)
            self._stop_output = [*self._stop_output, entry][-200:]
            self.query_one(ExecutionConsole).append(entry)

    async def _run_stop(self, targets: tuple[str, ...]) -> None:
        names = {item.id: item.name for item in self._inventory.values()}
        self._report_stop(
            "Stopping " + ", ".join(names.get(target, target[:12]) for target in targets) + "…"
        )
        try:
            result = await self.engine.stop_containers(targets, confirmed=True)
            details = "; ".join(f"{key[:12]}: {value}" for key, value in result.failed.items())
            for target in result.stopped:
                self._report_stop(f"{names.get(target, target[:12])} stopped.")
            for target, message in result.failed.items():
                self._report_stop(f"{names.get(target, target[:12])}: {message}", severity="error")
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
                self._report_stop(
                    "Wait cancelled; Docker may still stop targets.", severity="warning"
                )
                self.notify(
                    "Stop wait cancelled; Docker may still stop targets. No rollback.",
                    severity="warning",
                )
        except Exception:
            if not self._closing:
                self._report_stop("Outcome unknown; inspect Docker.", severity="error")
                self.notify(
                    "Stop outcome is unknown. Inspect Docker before retrying.", severity="warning"
                )
        finally:
            self._stopping.difference_update(targets)

    @staticmethod
    def _is_missing_image_failure(output: str) -> bool:
        return (
            re.search(r"(?m)^Error response from daemon: No such image: [^\s]+$", output)
            is not None
        )

    def _retry_profile_is_current(self, run: _ComposeRun) -> bool:
        """Whether the run's own launch profile still resolves to the plan it ran.

        The check is bound to the run, not to the current selection or bar state, so a
        consent stays valid while the user works with other projects.
        """
        profile, key = run.profile, run.profile_key
        if profile is None or key is None or self._launch_store is None:
            return False
        try:
            current = next(
                (
                    candidate
                    for index, candidate in enumerate(self._launch_store.profiles())
                    if not candidate.dynamic and self._launch_profile_key(candidate, index) == key
                ),
                None,
            )
            return (
                current is not None
                and current.raw == profile.raw
                and self._project_from_profile(current) == run.plan.project
            )
        except (ConfigurationError, ComposeError, OSError):
            return False

    async def _request_inline_download(self, run: _ComposeRun, fingerprint: str) -> bool:
        plan = run.plan
        async with self._bar_lock:
            # Never overwrite another pending confirmation; wait until the user answers it.
            while self._bar_has_pending() and not self._closing:
                self._bar_idle.clear()
                await self._bar_idle.wait()
            if self._closing:
                return False
            self._pending_retry_plan = plan
            self._pending_retry_fingerprint = fingerprint
            self.query_one("#inline-compose-message", Static).update(
                f"Missing image for {run.prefix} ({plan.project.project_name}). Download "
                f"missing images and retry {plan.action} / {_plan_scope(plan)}?"
            )
            self.query_one("#inline-compose").tooltip = plan.display
            self.query_one("#inline-compose-confirm", Button).label = "Download and retry"
            self.query_one("#inline-compose-confirm", Button).disabled = False
            self.query_one("#inline-compose-cancel", Button).label = "Cancel"
            self.query_one("#inline-compose-cancel", Button).disabled = False
            self.query_one("#inline-compose").display = True
            decision = asyncio.get_running_loop().create_future()
            self._retry_decision = decision
            self.query_one("#inline-compose-cancel", Button).focus()
            try:
                approved = await decision
                return (
                    approved is True
                    and self._pending_retry_plan is plan
                    and self._pending_retry_fingerprint == fingerprint
                )
            finally:
                # A preview opened right after the answer already replaced this consent;
                # clearing the bar then would silently drop that preview.
                owns_bar = self._pending_retry_plan is plan
                self._retry_decision = None
                self._pending_retry_plan = None
                self._pending_retry_fingerprint = None
                if owns_bar and not self._closing:
                    # The retry reports to the project's output; the bar is free again.
                    self._dismiss_inline_compose()
                    self.query_one(self._selection_table_selector(), DataTable).focus()

    async def _run_inline_compose(self, run: _ComposeRun) -> None:
        plan, service = run.plan, run.service
        self._begin_compose_output(run)
        streamed = [False]

        def record(text: str, *, severity: str = "unknown") -> None:
            self._record_compose_output(run, text, severity=severity)

        def receive_output(line: str) -> None:
            streamed[0] = True
            record(line)

        def retain_unstreamed_result(result) -> None:
            if not streamed[0] and result.output:
                self._write_compose_output(run, result.output)

        try:
            result = await service.run(plan, confirmed=True, on_output=receive_output)
            retain_unstreamed_result(result)
            record(
                f"Compose exited {result.exit_code}.",
                severity="info" if result.exit_code == 0 else "error",
            )
            if result.exit_code == 0:
                self._remember_compose_project(plan.project)
                await self._refresh_compose_logs(
                    plan, run.selection, run.selected_project, run.revision
                )
                self.notify(
                    f"Compose exited 0: {plan.project.project_name} / "
                    f"{_plan_scope(plan)}.",
                    severity="information",
                )
                return

            if not self._is_missing_image_failure(result.output):
                self.notify(
                    f"Compose exited {result.exit_code}: {plan.project.project_name} / "
                    f"{_plan_scope(plan)}. Inspect the central log viewer.",
                    severity="warning",
                )
                return

            if not self._retry_profile_is_current(run):
                record(
                    "Download retry unavailable because the launch profile changed.",
                    severity="error",
                )
                return
            try:
                retry_fingerprint = await service.capture_retry_environment(plan)
            except Exception:
                retry_fingerprint = None
            if not isinstance(retry_fingerprint, str) or not re.fullmatch(
                r"[0-9a-f]{64}", retry_fingerprint
            ):
                record(
                    "Missing-image retry unavailable: runtime inputs could not be verified.",
                    severity="error",
                )
                return
            if not self._retry_profile_is_current(run):
                record(
                    "Download retry unavailable because the launch profile changed.",
                    severity="error",
                )
                return

            approved = await self._request_inline_download(run, retry_fingerprint)
            if not approved or self._closing:
                record(
                    "Download retry cancelled; no image pull or second Compose run was started."
                )
                return
            if not self._retry_profile_is_current(run):
                record(
                    "Download retry cancelled because the launch profile changed.",
                    severity="error",
                )
                self.notify(
                    "Launch profile changed; download and retry cancelled.",
                    severity="warning",
                )
                return

            record(
                f"Retrying {plan.action} once with missing-image download explicitly authorized."
            )
            streamed[0] = False
            retry = await service.run(
                plan,
                confirmed=True,
                pull_missing=True,
                retry_fingerprint=retry_fingerprint,
                on_output=receive_output,
                retry_preflight=lambda: (
                    self._retry_profile_is_current(run) and not self._closing
                ),
            )
            retain_unstreamed_result(retry)
            record(
                f"Compose retry exited {retry.exit_code}.",
                severity="info" if retry.exit_code == 0 else "error",
            )
            if retry.exit_code == 0:
                self._remember_compose_project(plan.project)
                await self._refresh_compose_logs(
                    plan, run.selection, run.selected_project, run.revision
                )
                self.notify(
                    f"Compose retry exited 0: {plan.project.project_name} / "
                    f"{_plan_scope(plan)}.",
                    severity="information",
                )
            else:
                self.notify(
                    f"Compose retry exited {retry.exit_code}: {plan.project.project_name} / "
                    f"{_plan_scope(plan)}. Inspect the central log viewer.",
                    severity="warning",
                )
        except asyncio.CancelledError:
            if not self._closing:
                record(
                    "Compose operation stopped by user; Docker changes may remain.",
                    severity="warning",
                )
                self.notify(
                    "CLI stopped; Docker changes may remain. No rollback.", severity="warning"
                )
        except ComposeError as error:
            record(f"Compose failed: {error}", severity="error")
            self.notify(str(error), severity="warning")
        except Exception:
            record("Compose failed unexpectedly. Inspect Docker before retrying.", severity="error")
            self.notify("Compose failed. Inspect Docker before retrying.", severity="warning")

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
                    "#launch-profiles",
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

    @on(Button.Pressed, "#terminal-close")
    @on(Button.Pressed, "#container-terminal-close")
    async def terminal_close_pressed(self) -> None:
        await self.action_close_terminal()

    @on(Button.Pressed, "#inline-compose-cancel")
    def action_cancel_compose(self) -> None:
        if self._retry_decision is not None and not self._retry_decision.done():
            self.query_one("#inline-compose-confirm", Button).disabled = True
            self.query_one("#inline-compose-cancel", Button).disabled = True
            self._retry_decision.set_result(False)
        elif not self._bar_has_pending() and self._project_is_composing(self.selected_project):
            # Only the selected project's run stops; other projects keep running.
            self._compose_tasks[self.selected_project].cancel()
        elif self._credential_busy():
            self._credential_task.cancel()
        else:
            if self._logs_requested and not self.query_one("#container-shell").display:
                # Esc closes on-demand logs and returns to the details view.
                self._set_logs_requested(False)
                self.query_one(self._selection_table_selector(), DataTable).focus()
                return
            self._dismiss_inline_compose()
            self.query_one(self._selection_table_selector(), DataTable).focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "container_pane" and isinstance(self.focused, Input):
            # Inputs handle Ctrl+arrows themselves but not Option+arrows; typing in a
            # field must never move focus away from it.
            return False
        if action == "toggle_host_terminal" and (
            not self.is_mounted
            or self._host_terminal_pane is None
            or self.query_one(CodeWorkspace).display
            # Without a live shell, O opens one, so it follows H's availability rules.
            or (
                not self._host_terminal_pane.active
                and (not self._left_table_focused() or isinstance(self.screen, ModalScreen))
            )
        ):
            return False
        if self.is_mounted and self.query_one(CodeWorkspace).display and action in {
            "focus_logs", "retry_logs", "show_container_details", "toggle_compose_output",
            "toggle_project", "open_container_terminal", "open_host_terminal",
            "recreate_selected", "build_selected", "stop_selected", "cancel_compose",
            "compose", "start_project", "restart_selected", "rebuild_selected",
            "refresh_aws_credentials", "container_pane",
        }:
            return False
        if action in {
            "debug_code", "code_step_over", "code_step_in", "code_step_out",
            "toggle_code_terminal",
        } and (
            not self.is_mounted or not self.query_one(CodeWorkspace).display
            or isinstance(self.screen, ModalScreen)
        ):
            return False
        if action in {
            "run_code", "toggle_breakpoint", "edit_breakpoint", "toggle_area",
        } and isinstance(
            self.screen, ModalScreen
        ):
            return False
        if isinstance(self.focused, TerminalPane) and self.focused.active:
            # A live terminal owns the keys; once its process exits, shortcuts work again.
            return False
        if action in {"open_container_terminal", "open_host_terminal"} and (
            not self._left_table_focused() or isinstance(self.screen, ModalScreen)
        ):
            return False
        if action == "cancel_compose" and isinstance(self.screen, ModalScreen):
            return False
        if action in {"compose", "start_project"} and self._credential_busy():
            return False
        if action in {
            "quit",
            "retry_logs",
            "compose",
            "focus_logs",
            "restart_selected",
            "rebuild_selected",
            "recreate_selected",
            "build_selected",
            "open_launch_file",
            "stop_selected",
            "start_project",
        } and isinstance(self.screen, ModalScreen):
            return False
        if action in {
            "quit",
            "retry_logs",
            "restart_selected",
            "rebuild_selected",
            "recreate_selected",
            "build_selected",
            "stop_selected",
            "show_container_details",
            "toggle_compose_output",
            "toggle_project",
        } and isinstance(self.focused, Input):
            return False
        return True
