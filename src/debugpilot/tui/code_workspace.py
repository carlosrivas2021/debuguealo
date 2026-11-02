"""Registration-only Code area; execution and debugger controls are not wired yet."""

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, DataTable, Static

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.code_projects import CodeProjectStore


class CodeWorkspace(Vertical):
    def __init__(self):
        super().__init__(id="code-workspace")
        self.store = CodeProjectStore()

    def compose(self) -> ComposeResult:
        yield Static("PROJECTS", id="code-title")
        yield Static("", id="code-status", markup=False)
        yield Button("Reload code profiles", id="code-reload")
        yield DataTable(id="code-projects", cursor_type="row", zebra_stripes=True)
        yield Static(
            "Registration only. Run (F5), debug (Shift+F5) and source browsing arrive later.",
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
        try:
            profiles = self.store.profiles()
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
