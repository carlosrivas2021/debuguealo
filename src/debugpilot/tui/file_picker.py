"""Lazy terminal-only local Compose file selection."""

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Static


class ComposeFilePicker(ModalScreen[Path | None]):
    """Navigate explicitly; selecting a file never invokes Docker."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    ComposeFilePicker { align: center middle; background: $background 80%; }
    ComposeFilePicker > Vertical {
        width: 90%; height: 90%; border: round $accent; background: $surface; padding: 1;
    }
    ComposeFilePicker DirectoryTree { height: 1fr; }
    ComposeFilePicker Horizontal { height: 3; }
    ComposeFilePicker Static { height: auto; }
    """

    def __init__(self, root: Path | None = None):
        super().__init__()
        self.root_path = (root or Path.cwd()).resolve()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Open trusted Compose YAML · selecting does not start Docker")
            yield Input(str(self.root_path), id="file-path")
            yield DirectoryTree(self.root_path, id="file-tree")
            yield Static("Choose a .yaml/.yml file or enter an absolute path.", id="file-status")
            with Horizontal():
                yield Button("Up", id="file-up")
                yield Button("Open", id="file-open", variant="primary")
                yield Button("Cancel", id="file-cancel")

    def _choose(self, path: Path) -> None:
        try:
            if not path.is_absolute():
                raise ValueError
            path = path.resolve(strict=True)
            if path.is_dir():
                self.root_path = path
                self.query_one(DirectoryTree).path = path
                self.query_one(Input).value = str(path)
            elif path.is_file() and path.suffix.lower() in {".yaml", ".yml"}:
                self.dismiss(path)
            else:
                raise ValueError
        except (OSError, ValueError):
            self.query_one("#file-status", Static).update(
                "Choose an existing directory or an absolute .yaml/.yml file path."
            )

    @on(DirectoryTree.FileSelected)
    def file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        self._choose(event.path)

    @on(Input.Submitted)
    @on(Button.Pressed, "#file-open")
    def open_path(self) -> None:
        self._choose(Path(self.query_one(Input).value))

    @on(Button.Pressed, "#file-up")
    def up(self) -> None:
        self._choose(self.root_path.parent)

    @on(Button.Pressed, "#file-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)
