"""Explicit export of a dynamic configuration without replacing editor files."""

import copy
import json

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.launch_profiles import LaunchProfileStore


class SaveLaunchDialog(ModalScreen):
    BINDINGS = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    SaveLaunchDialog { align: center middle; background: $background 80%; }
    SaveLaunchDialog > VerticalScroll {
        width: 90%; max-width: 100; height: 90%; border: round $accent;
        background: $surface; padding: 1;
    }
    SaveLaunchDialog TextArea { height: 1fr; min-height: 5; }
    SaveLaunchDialog Static { height: auto; }
    SaveLaunchDialog Horizontal { height: 3; }
    SaveLaunchDialog Button { width: 1fr; }
    """

    def __init__(self, store: LaunchProfileStore, configuration: dict):
        super().__init__()
        self.store = store
        self.configuration = copy.deepcopy(configuration)
        self.configuration["source"] = "manual"
        self.configuration.pop("pendingReason", None)
        self.configuration.pop("discoveryHash", None)
        self.existing = store.path.exists()

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("SAVE LAUNCH CONFIGURATION")
            yield Static(str(self.store.path), markup=False)
            yield Input(value=self.configuration.get("name", ""), id="launch-save-name")
            yield Static(
                "File exists: copy this object into its configurations array in your editor. "
                "Existing files are never replaced."
                if self.existing
                else "Review and create launch.json. This does not run Compose.",
                id="launch-save-status",
                markup=False,
            )
            yield TextArea(self._json(), read_only=True, id="launch-save-json")
            with Horizontal():
                yield Button("Create launch.json", id="launch-save-confirm", disabled=self.existing)
                yield Button("Copy JSON", id="launch-save-copy")
                yield Button("Close", id="launch-save-close")

    def _json(self) -> str:
        # An external editor may have created the file since this modal opened.
        self.existing = self.existing or self.store.path.exists()
        value = (
            self.configuration
            if self.existing
            else {"version": 1, "configurations": [self.configuration]}
        )
        return json.dumps(value, ensure_ascii=False, indent=2) + "\n"

    @on(Input.Changed, "#launch-save-name")
    def rename(self, event: Input.Changed) -> None:
        self.configuration["name"] = event.value
        self.query_one("#launch-save-json", TextArea).text = self._json()

    @on(Button.Pressed, "#launch-save-confirm")
    def save(self) -> None:
        try:
            self.store.save_configuration(self.configuration)
        except ConfigurationError as error:
            self.query_one("#launch-save-json", TextArea).text = self._json()
            if self.existing:
                self.query_one("#launch-save-confirm", Button).disabled = True
            self.query_one("#launch-save-status", Static).update(str(error))
            return
        self.existing = True
        self.query_one("#launch-save-json", TextArea).text = self._json()
        self.query_one("#launch-save-confirm", Button).disabled = True
        self.query_one("#launch-save-status", Static).update("Saved. No Docker operation was run.")

    @on(Button.Pressed, "#launch-save-copy")
    def copy_json(self) -> None:
        contents = self._json()
        self.query_one("#launch-save-json", TextArea).text = contents
        if self.existing:
            self.query_one("#launch-save-confirm", Button).disabled = True
        self.app.copy_to_clipboard(contents)
        self.query_one("#launch-save-status", Static).update(
            "JSON sent to the terminal clipboard. Paste it in your editor; no file was changed."
        )

    @on(Button.Pressed, "#launch-save-close")
    def action_close(self) -> None:
        self.dismiss()
