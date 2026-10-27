import asyncio
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RichLog, Select, Static, TextArea

from debugpilot.core.models import ContainerInfo
from debugpilot.docker.compose import ComposeError, ComposePlan, ComposeProject, ComposeService


class ComposeDialog(ModalScreen):
    """Explicit configuration → preview → one confirmation for one operation."""

    BINDINGS = [Binding("escape", "cancel", "Close / stop CLI")]
    DEFAULT_CSS = """
    ComposeDialog { align: center middle; background: $background 80%; }
    ComposeDialog > VerticalScroll {
        width: 95%; max-width: 110; height: 95%; border: round $accent;
        background: $surface; padding: 0 1;
    }
    ComposeDialog Label { height: auto; }
    ComposeDialog TextArea { height: 4; }
    ComposeDialog Input, ComposeDialog Select { height: 3; }
    ComposeDialog .compose-buttons { height: 3; }
    ComposeDialog Button { width: 1fr; min-width: 12; }
    ComposeDialog #compose-status { height: auto; min-height: 2; color: $warning; }
    ComposeDialog #compose-command { height: auto; min-height: 2; }
    ComposeDialog RichLog { height: 6; }
    """

    def __init__(
        self,
        service: ComposeService,
        selected: ContainerInfo | None,
        *,
        selected_project: str | None = None,
        initial_action: str = "recreate",
    ):
        super().__init__()
        self.service = service
        self.selected = selected
        self.selected_project = selected.compose_project if selected else selected_project
        if initial_action not in {"restart", "recreate", "rebuild"}:
            raise ValueError("Unknown initial Compose action.")
        self.initial_action = initial_action
        self.plan: ComposePlan | None = None
        self._revision = 0
        self._operation: asyncio.Task | None = None
        self._leaving = False

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("COMPOSE · explicit local operation")
            yield Static(
                "Trusted projects only: builds/hooks may run code and access files/network. "
                "Recreation replaces container writable layers; running services are interrupted.",
                markup=False,
            )
            yield Label("Workspace directory (absolute path)")
            yield Input(placeholder="Path to your trusted project", id="compose-workspace")
            yield Label("Compose project name")
            yield Input(
                value=self.selected_project or "",
                placeholder="Explicit project name",
                id="compose-project",
            )
            yield Label("Compose YAML files in override order (one path per line)")
            yield TextArea("compose.yaml", id="compose-files")
            yield Select(
                [
                    ("Recreate · reload environment", "recreate"),
                    ("Rebuild and recreate · --build", "rebuild"),
                    ("Restart · existing environment only", "restart"),
                ],
                value=self.initial_action,
                allow_blank=False,
                id="compose-action",
            )
            selected_service = (
                self.selected.compose_service if self.selected and self.selected_project else None
            )
            yield Select(
                [
                    (f"Selected service: {selected_service or 'unavailable'}", "service"),
                    ("Entire Compose project (all configured services)", "project"),
                ],
                value="service" if selected_service else "project",
                allow_blank=False,
                id="compose-scope",
            )
            yield Static(
                "Preview required. No Docker operation has run.", id="compose-status", markup=False
            )
            yield Static("", id="compose-command", markup=False)
            with Horizontal(classes="compose-buttons"):
                yield Button("Preview", id="compose-preview")
                yield Button(
                    "Confirm & run", variant="warning", disabled=True, id="compose-confirm"
                )
                yield Button("Close / stop", id="compose-cancel")
            yield RichLog(
                id="compose-output",
                max_lines=2000,
                wrap=True,
                min_width=1,
                markup=False,
                highlight=False,
            )

    @on(Input.Changed)
    @on(Select.Changed)
    @on(TextArea.Changed)
    def invalidate(self) -> None:
        self._revision += 1
        self.plan = None
        self.query_one("#compose-confirm", Button).disabled = True
        self.query_one("#compose-command", Static).update("")

    @on(Button.Pressed, "#compose-preview")
    async def preview(self) -> None:
        self.plan = None
        self.query_one("#compose-confirm", Button).disabled = True
        revision = self._revision
        workspace = Path(self.query_one("#compose-workspace", Input).value)
        files = tuple(
            Path(line.strip())
            for line in self.query_one(TextArea).text.splitlines()
            if line.strip()
        )
        project_name = self.query_one("#compose-project", Input).value
        action = str(self.query_one("#compose-action", Select).value)
        scope = self.query_one("#compose-scope", Select).value
        try:
            if not workspace.is_absolute():
                raise ComposeError("Choose an absolute workspace directory.")
            if self.selected_project is not None and project_name != self.selected_project:
                raise ComposeError("Selected group belongs to a different Compose project.")
            target = None
            if scope == "service":
                if not self.selected or not self.selected.compose_service:
                    raise ComposeError("The selected container has no Compose service metadata.")
                if project_name != self.selected.compose_project:
                    raise ComposeError("Selected service belongs to a different Compose project.")
                target = self.selected.compose_service
            project = await asyncio.to_thread(ComposeProject.create, workspace, files, project_name)
            plan = await asyncio.to_thread(self.service.preview, project, action, target)
        except ComposeError as error:
            self.query_one("#compose-status", Static).update(str(error))
            return
        if revision != self._revision or self._leaving:
            return
        self.plan = plan
        self.query_one("#compose-command", Static).update(plan.display)
        self.query_one("#compose-status", Static).update(
            f"Target: {project_name} / {target or 'ENTIRE PROJECT'}. "
            + ("Includes hidden/stopped services. " if target is None else "")
            + "Confirm interrupts services. Restart does NOT reload environment. "
            "No automatic rollback; inspect Docker after a failure or interruption."
        )
        self.query_one("#compose-confirm", Button).disabled = False

    def _set_busy(self, busy: bool) -> None:
        for widget in self.query("Input, Select, TextArea, #compose-preview"):
            widget.disabled = busy
        self.query_one("#compose-confirm", Button).disabled = True

    @on(Button.Pressed, "#compose-confirm")
    def confirm(self) -> None:
        if self.plan is None or (self._operation is not None and not self._operation.done()):
            return
        plan, self.plan = self.plan, None
        self._set_busy(True)
        self.query_one("#compose-status", Static).update(
            "Compose is running (up to 10 minutes). Stop kills the CLI, not Docker rollback."
        )
        self._operation = asyncio.create_task(self._execute(plan))

    async def _execute(self, plan: ComposePlan) -> None:
        try:
            result = await self.service.run(plan, confirmed=True)
            if not self._leaving:
                output = self.query_one(RichLog)
                output.clear()
                output.write(Text(result.output), width=max(1, output.size.width))
                self.query_one("#compose-status", Static).update(
                    f"Compose exited {result.exit_code}. "
                    "Review the output and refreshed inventory; "
                    "a failure may leave partial changes."
                )
        except asyncio.CancelledError:
            if not self._leaving:
                self.query_one("#compose-status", Static).update(
                    "CLI stopped. Docker builds or changed containers may remain; "
                    "inspect before retry."
                )
        except ComposeError as error:
            if not self._leaving:
                self.query_one("#compose-status", Static).update(str(error))
        except Exception:
            if not self._leaving:
                self.query_one("#compose-status", Static).update(
                    "Compose failed unexpectedly. Inspect Docker before retrying."
                )
        finally:
            if not self._leaving:
                self._set_busy(False)

    @on(Button.Pressed, "#compose-cancel")
    async def action_cancel(self) -> None:
        if self._operation is not None and not self._operation.done():
            self._operation.cancel()
            await asyncio.gather(self._operation, return_exceptions=True)
        else:
            self.dismiss()

    async def on_unmount(self) -> None:
        self._leaving = True
        if self._operation is not None and not self._operation.done():
            self._operation.cancel()
            await asyncio.gather(self._operation, return_exceptions=True)
