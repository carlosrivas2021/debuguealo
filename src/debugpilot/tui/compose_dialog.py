import asyncio
from collections.abc import Callable
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RichLog, Select, Static, TextArea

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.core.models import ContainerInfo
from debugpilot.docker.compose import ComposeError, ComposePlan, ComposeProject, ComposeService
from debugpilot.storage.launch_profiles import LaunchProfile, LaunchProfileStore
from debugpilot.tui.file_picker import ComposeFilePicker


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
    ComposeDialog.quick > VerticalScroll { height: auto; max-height: 90%; }
    """

    def __init__(
        self,
        service: ComposeService,
        selected: ContainerInfo | None,
        *,
        selected_project: str | None = None,
        initial_action: str = "recreate",
        browse_on_mount: bool = False,
        remembered_project: ComposeProject | None = None,
        quick: bool = False,
        remember_project: Callable[[ComposeProject], None] | None = None,
        launch_profiles: list[LaunchProfile] | None = None,
        resolve_profile: Callable[[LaunchProfile], ComposeProject] | None = None,
        profile_selected: Callable[[str, str], None] | None = None,
        launch_store: LaunchProfileStore | None = None,
    ):
        super().__init__()
        self.service = service
        self.selected = selected
        self.selected_project = selected.compose_project if selected else selected_project
        if initial_action not in {"start", "restart", "recreate", "rebuild"}:
            raise ValueError("Unknown initial Compose action.")
        self.initial_action = initial_action
        self.browse_on_mount = browse_on_mount
        self.remembered_project = remembered_project
        self.quick = quick and remembered_project is not None
        self.set_class(self.quick, "quick")
        self.remember_project = remember_project
        self.launch_profiles = launch_profiles or []
        self.resolve_profile = resolve_profile
        self.profile_selected = profile_selected
        self.launch_store = launch_store
        self._selected_launch: LaunchProfile | None = None
        self._profile_project: ComposeProject | None = None
        self._paths_visible = True
        self._resolve_identity = initial_action == "start"
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
            if self.launch_profiles:
                yield Label("Launch profile")
                yield Select(
                    [
                        (p.name or f"Unnamed profile {i + 1}", p.name or str(i))
                        for i, p in enumerate(self.launch_profiles)
                    ],
                    prompt="Choose a launch profile",
                    id="compose-profile",
                )
            yield Button("Browse Compose file", id="compose-browse")
            yield Button("Edit paths", id="compose-edit-paths")
            yield Label("Workspace directory (absolute path)", id="compose-workspace-label")
            yield Input(placeholder="Path to your trusted project", id="compose-workspace")
            yield Label("Compose project name", id="compose-project-label")
            yield Input(
                value=self.selected_project or "",
                placeholder="Explicit project name",
                id="compose-project",
            )
            yield Label(
                "Compose YAML files in override order (one path per line)", id="compose-files-label"
            )
            yield TextArea("compose.yaml", id="compose-files")
            yield Label(
                "Compose project directory (optional; first file directory)",
                id="compose-directory-label",
            )
            yield Input(
                id="compose-project-directory", placeholder="Default: first Compose file folder"
            )
            yield Select(
                [
                    ("Start project - no forced recreation", "start"),
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
                if self.launch_store is not None:
                    yield Button("Save Configuration", id="compose-save-profile")
                yield Button("Close / stop", id="compose-cancel")
            yield RichLog(
                id="compose-output",
                max_lines=2000,
                wrap=True,
                min_width=1,
                markup=False,
                highlight=False,
            )

    def on_mount(self) -> None:
        self.query_one("#compose-edit-paths").display = False
        if self.remembered_project is not None:
            self.query_one("#compose-workspace", Input).value = str(
                self.remembered_project.workspace
            )
            self.query_one(TextArea).text = "\n".join(map(str, self.remembered_project.files))
            self._profile_project = self.remembered_project
            self.query_one("#compose-project-directory", Input).value = str(
                self.remembered_project.project_directory or ""
            )
        if len(self.launch_profiles) == 1:
            profile = self.launch_profiles[0]
            self.query_one("#compose-profile", Select).value = profile.name or "0"
        if self.quick:
            for widget in self.query("Input, Select, TextArea, #compose-browse, #compose-preview"):
                widget.display = False
            for label in list(self.query(Label))[1:]:
                label.display = False
            self.call_after_refresh(self.preview)
        if self.browse_on_mount:
            self.call_after_refresh(self.browse)

    @on(Select.Changed, "#compose-profile")
    def choose_launch_profile(self, event: Select.Changed) -> None:
        value = event.value
        profile = next(
            (p for i, p in enumerate(self.launch_profiles) if (p.name or str(i)) == value), None
        )
        if profile is None or self.resolve_profile is None:
            return
        self.invalidate()
        try:
            project = self.resolve_profile(profile)
        except (ConfigurationError, ComposeError) as error:
            self._profile_project = None
            self.query_one("#compose-status", Static).update(f"Launch profile pending: {error}")
            return
        self._profile_project = project
        self._selected_launch = profile
        self.query_one("#compose-workspace", Input).value = str(project.workspace)
        self.query_one("#compose-project", Input).value = project.project_name
        self.query_one("#compose-project-directory", Input).value = str(
            project.project_directory or ""
        )
        self.query_one(TextArea).text = "\n".join(map(str, project.files))
        self._set_paths_visible(False)
        if self.profile_selected is not None and profile.name is not None:
            self.profile_selected(profile.name, project.project_name)
        self.query_one("#compose-status", Static).update(
            "Profile loaded. Preview and confirm to run."
        )
        self.call_after_refresh(self.query_one("#compose-preview").scroll_visible, animate=False)

    def _set_paths_visible(self, visible: bool) -> None:
        self._paths_visible = visible
        for widget in self.query(
            "Input, TextArea, #compose-browse, #compose-workspace-label, "
            "#compose-project-label, #compose-files-label, #compose-directory-label"
        ):
            widget.display = visible
        self.query_one("#compose-edit-paths").display = True
        self.query_one("#compose-edit-paths", Button).label = (
            "Hide paths" if visible else "Edit paths"
        )

    @on(Button.Pressed, "#compose-edit-paths")
    def edit_profile_paths(self) -> None:
        self._set_paths_visible(not self._paths_visible)

    @on(Button.Pressed, "#compose-save-profile")
    def save_configuration(self) -> None:
        if self.launch_store is None or (
            self._operation is not None and not self._operation.done()
        ):
            return
        from debugpilot.tui.launch_save import SaveLaunchDialog

        raw = dict(self._selected_launch.raw) if self._selected_launch else {}
        project = self.query_one("#compose-project", Input).value.strip()
        raw.update(
            name=raw.get("name") or f"Compose: {project}",
            type="docker-compose",
            projectName=project,
            # The workspace input is a safety boundary, not a loaded profile's cwd.
            cwd=raw.get("cwd")
            if self._selected_launch
            else self.query_one("#compose-workspace", Input).value,
            files=[
                line.strip()
                for line in self.query_one("#compose-files", TextArea).text.splitlines()
                if line.strip()
            ],
        )
        directory = self.query_one("#compose-project-directory", Input).value.strip()
        if directory:
            raw["projectDirectory"] = directory
        else:
            raw.pop("projectDirectory", None)
        self.app.push_screen(SaveLaunchDialog(self.launch_store, raw))

    @on(Button.Pressed, "#compose-browse")
    def browse(self) -> None:
        if self._operation is not None and not self._operation.done():
            return
        self.app.push_screen(ComposeFilePicker(), self._file_chosen)

    def _file_chosen(self, file: Path | None) -> None:
        if file is None:
            return
        self._resolve_identity = True
        self._profile_project = None
        self._selected_launch = None
        self.query_one("#compose-workspace", Input).value = str(file.parent)
        self.query_one(TextArea).text = str(file)
        self.invalidate()
        self.query_one("#compose-status", Static).update(
            "Trusted file selected. Preview inspects Compose configuration read-only; "
            "Confirm is still required to start or change containers."
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
    def preview(self) -> None:
        if self._operation is None or self._operation.done():
            self._operation = asyncio.create_task(self._preview())

    async def _preview(self) -> None:
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
        directory = self.query_one("#compose-project-directory", Input).value.strip()
        try:
            if not workspace.is_absolute():
                raise ComposeError("Choose an absolute workspace directory.")
            absolute_files = tuple((workspace / path).resolve() for path in files)
            project_directory = (
                Path(directory)
                if directory
                else (absolute_files[0].parent if absolute_files else None)
            )
            extras = {}
            if project_directory is not None and project_directory != workspace:
                extras["project_directory"] = project_directory
            if self._profile_project is not None:
                extras.update(
                    project_directory=project_directory,
                    process_cwd=self._profile_project.process_cwd,
                    environment_files=self._profile_project.environment_files,
                    up=self._profile_project.up,
                )
            if (self._resolve_identity or action == "start") and self._profile_project is None:
                project = await self.service.inspect_project(workspace, files, **extras)
                if revision != self._revision or self._leaving:
                    return
                project_name = project.project_name
                with self.prevent(Input.Changed):
                    self.query_one("#compose-project", Input).value = project_name
            else:
                project = await asyncio.to_thread(
                    ComposeProject.create, workspace, files, project_name, **extras
                )
            if self.selected_project is not None and project_name != self.selected_project:
                raise ComposeError("Selected group belongs to a different Compose project.")
            target = None
            if scope == "service":
                if not self.selected or not self.selected.compose_service:
                    raise ComposeError("The selected container has no Compose service metadata.")
                if project_name != self.selected.compose_project:
                    raise ComposeError("Selected service belongs to a different Compose project.")
                target = self.selected.compose_service
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
        for widget in self.query(
            "Input, Select, TextArea, #compose-preview, #compose-browse, #compose-save-profile"
        ):
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
            if result.exit_code == 0 and self.remember_project is not None:
                self.remember_project(plan.project)
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
