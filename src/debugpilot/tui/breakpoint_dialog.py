"""Edit one breakpoint's condition and log message (logpoint)."""

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from debugpilot.storage.breakpoints import BreakpointOptions, breakpoint_options

HELP = (
    "Leave both fields empty for a plain breakpoint. A log message makes a logpoint: it "
    "writes to the debug output and does not stop. Use {expression} to include values."
)


class BreakpointDialog(ModalScreen[tuple[str, BreakpointOptions | None] | None]):
    """Dismisses with ("save", options), ("remove", None), or None when cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    BreakpointDialog { align: center middle; background: $background 80%; }
    BreakpointDialog > Vertical {
        width: 90%; max-width: 80; height: auto; border: round $accent;
        background: $surface; padding: 1;
    }
    BreakpointDialog Static { height: auto; }
    BreakpointDialog #breakpoint-status { color: $error; }
    BreakpointDialog Horizontal { height: 3; margin-top: 1; }
    BreakpointDialog Button { width: 1fr; }
    """

    def __init__(self, location: str, options: BreakpointOptions | None, exists: bool):
        super().__init__()
        self.location = location
        self.options = options
        self.exists = exists

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"BREAKPOINT · {self.location}")
            yield Static(HELP, markup=False)
            yield Label("Condition")
            yield Input(
                value=(self.options.condition or "") if self.options else "",
                placeholder="user_id == 42",
                id="breakpoint-condition",
            )
            yield Label("Log message")
            yield Input(
                value=(self.options.log_message or "") if self.options else "",
                placeholder="order {order.id} received",
                id="breakpoint-log",
            )
            yield Static("", id="breakpoint-status", markup=False)
            with Horizontal():
                yield Button("Save", id="breakpoint-save", variant="primary")
                yield Button("Remove", id="breakpoint-remove", disabled=not self.exists)
                yield Button("Cancel", id="breakpoint-cancel")

    def on_mount(self) -> None:
        self.query_one("#breakpoint-condition", Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#breakpoint-save")
    def save_breakpoint(self) -> None:
        try:
            options = breakpoint_options(
                self.query_one("#breakpoint-condition", Input).value,
                self.query_one("#breakpoint-log", Input).value,
            )
        except ValueError as error:
            self.query_one("#breakpoint-status", Static).update(str(error))
            return
        self.dismiss(("save", options))

    @on(Button.Pressed, "#breakpoint-remove")
    def remove_breakpoint(self) -> None:
        self.dismiss(("remove", None))

    @on(Button.Pressed, "#breakpoint-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)
