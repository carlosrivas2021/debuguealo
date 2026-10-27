import asyncio
from contextlib import aclosing

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Static

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import DebugPilotError
from debugpilot.core.models import ContainerInfo
from debugpilot.tui.log_viewer import LogViewer


class DebugPilotApp(App):
    """The terminal owns its UI tasks; Docker operations stay behind the engine."""

    TITLE = "DebugPilot"
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+l", "focus_logs", "Logs"),
        Binding("r", "retry_logs", "Retry logs"),
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
        self._inventory: dict[str, ContainerInfo] = {}
        self._inventory_loaded = False
        self._selection_changed = asyncio.Event()
        self._generation = 0
        self._closing = False
        self._ui_tasks: list[asyncio.Task] = []
        self._stream_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Static("DebugPilot  ·  Docker: connecting…", id="docker-state", markup=False)
        with Horizontal(id="dashboard"):
            with Vertical(id="sidebar"):
                yield DataTable(id="containers", cursor_type="row", zebra_stripes=True)
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
        table.add_columns("Container", "State", "Compose")
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
                self.query_one("#docker-state", Static).update(
                    f"DebugPilot  ·  Docker: connected  ·  {len(inventory)} containers"
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

    def _show_inventory(self, inventory: list[ContainerInfo]) -> None:
        current = {item.id: item for item in inventory}
        if self._inventory_loaded and current == self._inventory:
            return
        self._inventory_loaded = True
        previous = self.selected_container
        self._inventory = current
        table = self.query_one("#containers", DataTable)
        table.clear()
        for item in inventory:
            state = Text(item.state, style="green" if item.state == "running" else "yellow")
            compose = "/".join(filter(None, (item.compose_project, item.compose_service))) or "—"
            table.add_row(Text(item.name), state, Text(compose), key=item.id)
        selected = current.get(previous.id) if previous else None
        selected = selected or next(iter(current.values()), None)
        if selected:
            table.move_cursor(row=list(current).index(selected.id))
        self._select(selected)

    @on(DataTable.RowHighlighted, "#containers")
    def container_highlighted(self, event: DataTable.RowHighlighted) -> None:
        table = self.query_one("#containers", DataTable)
        if table.row_count:
            # Rebuilding inventory can enqueue old highlight events; accept only
            # the row that is still under the cursor, not an obsolete selection.
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            if event.row_key.value == key:
                self._select(self._inventory.get(key))

    def _select(self, item: ContainerInfo | None, *, force: bool = False) -> None:
        old = self.selected_container
        self.selected_container = item
        self.query_one("#container-info", Static).update(
            Text(
                f"{item.image}\n{item.id[:12]} · {item.state}\n"
                f"Compose: {item.compose_project or '—'} / {item.compose_service or '—'}"
            )
            if item
            else "No containers found; waiting for Docker inventory."
        )
        if force or old != item:
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
                    self.query_one("#log-state", Static).update("No container selected")
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
            message = f"Logs · {item.name} · stream ended (R to retry)"
        except DebugPilotError as error:
            message = f"Logs · {item.name} · {error} (R to retry)"
        except Exception:
            message = f"Logs · {item.name} · unable to read logs (R to retry)"
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
            self._select(self.selected_container, force=True)

    def action_debugger_unavailable(self) -> None:
        self.notify("Debugger controls arrive with DAP integration (T4–T5).")

    def action_compose(self) -> None:
        from debugpilot.docker.compose import ComposeService
        from debugpilot.tui.compose_dialog import ComposeDialog

        self.push_screen(
            ComposeDialog(ComposeService(self.engine.settings), self.selected_container)
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"quit", "retry_logs", "compose", "focus_logs"} and isinstance(
            self.screen, ModalScreen
        ):
            return False
        if action in {"quit", "retry_logs"} and isinstance(self.focused, Input):
            return False
        return True
