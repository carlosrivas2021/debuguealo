"""Full-width host Bash docked under the dashboard, apart from the Compose output card."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from debugpilot.tui.terminal_view import TerminalPane


class HostTerminal(Vertical):
    def __init__(self, *, escape_hook=None, exit_hook=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.terminal_pane = TerminalPane(
            id="terminal-pane", escape_hook=escape_hook, exit_hook=exit_hook
        )

    def compose(self) -> ComposeResult:
        with Horizontal(id="host-terminal-controls"):
            yield Static(
                "Terminal inactive · C container shell · T host Bash",
                id="terminal-context",
                markup=False,
            )
        yield self.terminal_pane

    def set_terminal_status(self, status: str) -> None:
        self.query_one("#terminal-context", Static).update(status)
