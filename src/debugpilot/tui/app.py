import asyncio
from contextlib import aclosing
from dataclasses import replace

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Checkbox, DataTable, Footer, Input, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import DebugPilotError
from debugpilot.core.models import ContainerInfo
from debugpilot.tui.container_list import ContainerRow, container_rows
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
        Binding("ctrl+o", "compose", "Compose"),
        *[
            Binding(key, "debugger_unavailable", show=False)
            for key in ("f5", "f9", "f10", "f11", "shift+f11")
        ],
    ]

    def __init__(self, engine: DebugPilotEngine, *, refresh_interval: float = 2):
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
        self._selection_changed = asyncio.Event()
        self._generation = 0
        self._closing = False
        self._ui_tasks: list[asyncio.Task] = []
        self._stream_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Static("DebugPilot  ·  Docker: connecting…", id="docker-state", markup=False)
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
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#containers", DataTable)
        table.add_columns("Project / container", "State", "Service")
        self.query_one("#stopped-containers", DataTable).add_columns(
            "Project / container", "State", "Service"
        )
        table.focus()
        await self.engine.start()
        self._ui_tasks = [
            asyncio.create_task(self._refresh_loop()),
            asyncio.create_task(self._selection_loop()),
        ]

    def on_resize(self) -> None:
        self.set_class(self.size.width < 100 or self.size.height < 28, "compact")

    async def _refresh_loop(self) -> None:
        while not self._closing:
            try:
                inventory = await self.engine.list_containers()
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

    def _show_inventory(self, inventory: list[ContainerInfo], *, force: bool = False) -> None:
        current = {item.id: item for item in inventory}
        if self._inventory_loaded and current == self._inventory and not force:
            return
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
            table.clear()
            for row in entries:
                style = "green" if row.state == "running" else "yellow"
                if row.container is None:
                    style = "bold cyan"
                table.add_row(
                    Text(row.label, style="bold" if row.container is None else ""),
                    Text(row.state, style=style),
                    Text(row.service),
                    key=row.key,
                )
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
        table = event.data_table
        if table.row_count and table.has_focus and not self._closing:
            # Rebuilding inventory can enqueue old highlight events; accept only
            # the row that is still under the cursor, not an obsolete selection.
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            if event.row_key.value == key:
                row = self._rows.get(key)
                if row is not None:
                    self._select(row.container, project=row.project, row_key=row.key)

    def _select(
        self,
        item: ContainerInfo | None,
        *,
        project: str | None = None,
        row_key: str | None = None,
        force: bool = False,
    ) -> None:
        old = (self.selected_container, self.selected_project, self._selection_key)
        self.selected_container = item
        self.selected_project = item.compose_project if item is not None else project
        self._selection_key = row_key or (f"container:{item.id}" if item is not None else None)
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
                "Select a service for logs; Ctrl+O acts on this project."
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
        if force or old != (item, self.selected_project, self._selection_key):
            self._generation += 1
            self._selection_changed.set()

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
                if item is None:
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

    async def _consume(self, item: ContainerInfo, generation: int) -> None:
        try:
            async with aclosing(
                self.engine.stream_logs(item.id, tail=100, follow=item.state == "running")
            ) as entries:
                async for entry in entries:
                    if self._generation == generation and not self._closing:
                        self.query_one(LogViewer).append(entry)
            message = f"Logs · {item.name} · stream ended (Ctrl+R to retry)"
        except DebugPilotError as error:
            message = f"Logs · {item.name} · {error} (Ctrl+R to retry)"
        except Exception:
            message = f"Logs · {item.name} · unable to read logs (Ctrl+R to retry)"
        if self._generation == generation and not self._closing:
            self.query_one("#log-state", Static).update(message)

    async def on_unmount(self) -> None:
        self._closing = True
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
        if self.selected_container:
            self._select(self.selected_container, row_key=self._selection_key, force=True)

    def action_debugger_unavailable(self) -> None:
        self.notify("Debugger controls arrive with DAP integration (T4–T5).")

    def action_compose(self) -> None:
        self._open_compose()

    def action_restart_selected(self) -> None:
        self._open_compose("restart", contextual=True)

    def action_rebuild_selected(self) -> None:
        self._open_compose("rebuild", contextual=True)

    def _open_compose(self, initial_action: str = "recreate", *, contextual: bool = False) -> None:
        from debugpilot.docker.compose import ComposeService
        from debugpilot.tui.compose_dialog import ComposeDialog

        if contextual and (
            not self.selected_project
            or (self.selected_container is not None and not self.selected_container.compose_service)
        ):
            self.notify(
                "Select a Compose project or service before restarting or rebuilding.",
                severity="warning",
            )
            return
        self.push_screen(
            ComposeDialog(
                ComposeService(self.engine.settings),
                self.selected_container,
                selected_project=self.selected_project,
                initial_action=initial_action,
            )
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {
            "quit",
            "retry_logs",
            "compose",
            "focus_logs",
            "restart_selected",
            "rebuild_selected",
        } and isinstance(self.screen, ModalScreen):
            return False
        if action in {"quit", "retry_logs", "restart_selected", "rebuild_selected"} and isinstance(
            self.focused, Input
        ):
            return False
        return True
