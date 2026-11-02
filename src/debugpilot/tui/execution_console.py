"""Docked Compose transcript and real terminal, kept separate from container logs."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, RichLog, Static

from debugpilot.core.models import LogEntry
from debugpilot.tui.terminal_view import TerminalPane


class ExecutionConsole(Vertical):
    DEFAULT_CSS = """
    ExecutionConsole { height: 12; min-height: 7; border-top: solid #2b3439; }
    ExecutionConsole #compose-output-heading { height: 1; color: #a9c2cc; }
    ExecutionConsole #console-controls { height: 1; }
    ExecutionConsole #compose-output-toggle { width: 20; height: 1; }
    ExecutionConsole #compose-output-viewer { height: 1fr; }
    ExecutionConsole RichLog.hidden { display: none; }
    ExecutionConsole #terminal-context { width: 1fr; height: 1; color: #9ba5aa; }
    ExecutionConsole #terminal-close { width: 18; height: 1; }
    ExecutionConsole #terminal-pane { height: 4; min-height: 2; border-top: solid #2b3439; }
    ExecutionConsole.output-hidden { height: 8; min-height: 6; }
    ExecutionConsole.output-hidden #compose-output-viewer { display: none; }
    """

    def __init__(self, *, escape_hook=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.terminal_pane = TerminalPane(id="terminal-pane", escape_hook=escape_hook)

    def compose(self) -> ComposeResult:
        yield Static("Compose execution output", id="compose-output-heading", markup=False)
        with Horizontal(id="console-controls"):
            yield Button("Hide output · O", id="compose-output-toggle")
            yield Static(
                "Terminal inactive · C container shell · H host Bash",
                id="terminal-context",
                markup=False,
            )
            yield Button("Close terminal", id="terminal-close")
        yield self.terminal_pane
        yield Static(
            "No Compose execution yet. Select a profile and press R to preview Recreate.",
            id="compose-empty",
            markup=False,
        )
        yield RichLog(id="compose-output-viewer", wrap=True, markup=False, auto_scroll=True)

    def append(self, entry: LogEntry) -> None:
        self.query_one("#compose-empty").set_class(True, "hidden")
        self.query_one("#compose-output-viewer", RichLog).write(entry.text)

    def clear(self) -> None:
        self.query_one("#compose-output-viewer", RichLog).clear()
        self.query_one("#compose-empty").set_class(False, "hidden")

    def set_output_visible(self, visible: bool) -> None:
        self.display = visible
        viewer = self.query_one("#compose-output-viewer", RichLog)
        viewer.display = visible
        button = self.query_one("#compose-output-toggle", Button)
        button.label = "Hide output · O" if visible else "Show output · O"
        button.tooltip = (
            "Compose transcript is hidden; activate to restore it." if not visible else ""
        )
        self.set_class(not visible, "output-hidden")

    def set_terminal_status(self, status: str) -> None:
        self.query_one("#terminal-context", Static).update(status)
        self.set_class(self.terminal_pane.active, "terminal-active")
