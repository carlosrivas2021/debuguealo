"""Compose transcript card, kept separate from container logs and the host terminal."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, RichLog, Static

from debugpilot.core.models import LogEntry


class ExecutionConsole(Vertical):
    DEFAULT_CSS = """
    ExecutionConsole { height: 12; min-height: 7; }
    ExecutionConsole #compose-output-heading { height: 1; color: #a9c2cc; }
    ExecutionConsole #console-controls { height: 1; align-horizontal: right; }
    ExecutionConsole #compose-output-toggle { width: 5; min-width: 5; height: 1; }
    ExecutionConsole #compose-output-viewer { height: 1fr; }
    ExecutionConsole RichLog.hidden { display: none; }
    ExecutionConsole.output-hidden { height: 3; min-height: 3; }
    ExecutionConsole.output-hidden #compose-output-viewer { display: none; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Compose execution output", id="compose-output-heading", markup=False)
        yield Static(
            "No Compose execution yet. Select a profile and press R to preview Recreate.",
            id="compose-empty",
            markup=False,
        )
        yield RichLog(id="compose-output-viewer", wrap=True, markup=False, auto_scroll=True)
        # Bottom-right toggle; the card never disappears, it only collapses.
        with Horizontal(id="console-controls"):
            yield Button("▴", id="compose-output-toggle")

    def on_mount(self) -> None:
        self.border_title = "Output"
        if not self.has_class("expanded"):
            self.set_output_visible(False)

    def append(self, entry: LogEntry) -> None:
        self.query_one("#compose-empty").set_class(True, "hidden")
        self.query_one("#compose-output-viewer", RichLog).write(entry.text)

    def clear(self) -> None:
        self.query_one("#compose-output-viewer", RichLog).clear()
        self.query_one("#compose-empty").set_class(False, "hidden")

    @property
    def expanded(self) -> bool:
        return self.has_class("expanded")

    def set_output_visible(self, visible: bool) -> None:
        """Expand the card to show the transcript, or collapse it to its title bar."""
        viewer = self.query_one("#compose-output-viewer", RichLog)
        viewer.display = visible
        button = self.query_one("#compose-output-toggle", Button)
        button.label = "▾" if visible else "▴"
        button.tooltip = "Minimize the output." if visible else "Expand the output."
        self.set_class(not visible, "output-hidden")
        self.set_class(visible, "expanded")
        if self.parent is not None:
            # Lets the panel above take the free space so the collapsed bar sinks down.
            self.parent.set_class(not visible, "output-collapsed")
