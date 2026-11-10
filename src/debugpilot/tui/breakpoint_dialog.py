"""Edit one breakpoint's condition and log message (logpoint) without hiding the line."""

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from debugpilot.storage.breakpoints import BreakpointOptions, breakpoint_options

HINT = "Enter save · Esc cancel · F9 removes the breakpoint"
MAX_TITLE_CODE = 60
# Border plus three rows; fixed so the panel can be placed before its first frame.
DIALOG_ROWS = 5


class BreakpointDialog(ModalScreen[tuple[str, BreakpointOptions | None] | None]):
    """A short panel placed where the read-only breakpoint panel sits, below the line.

    Dismisses with ("save", options), where None means a plain breakpoint, or None
    when cancelled. Removing a breakpoint stays on F9.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    BreakpointDialog { align: center bottom; background: transparent; }
    BreakpointDialog #breakpoint-box {
        width: 100%; max-width: 110; height: 5; border: round $accent;
        background: $surface; padding: 0 1;
    }
    BreakpointDialog Horizontal { height: 1; }
    BreakpointDialog Label { width: 5; color: $text-muted; }
    BreakpointDialog Input { width: 1fr; }
    BreakpointDialog #breakpoint-status { height: 1; color: $text-muted; }
    BreakpointDialog #breakpoint-status.error { color: $error; }
    """

    def __init__(self, location: str, code: str, options: BreakpointOptions | None,
                 anchor: tuple[int, int, int] | None = None):
        super().__init__()
        self.location = location
        self.code = " ".join(code.split())
        self.options = options
        # (x, bottom, width) on screen: the read-only panel's place, so both share it.
        self.anchor = anchor

    def compose(self) -> ComposeResult:
        with Vertical(id="breakpoint-box") as box:
            if self.anchor is not None:
                # Placed now, not after layout, so it never appears elsewhere first.
                x, bottom, width = self.anchor
                self.styles.align = ("left", "top")
                box.styles.width = width
                box.styles.max_width = width
                box.styles.height = DIALOG_ROWS
                box.styles.offset = (x, max(0, bottom - DIALOG_ROWS))
            code = self.code
            if len(code) > MAX_TITLE_CODE:
                code = code[:MAX_TITLE_CODE - 1] + "…"
            box.border_title = f"{self.location} · {code}" if code else self.location
            with Horizontal():
                yield Label("if")
                yield Input(
                    value=(self.options.condition or "") if self.options else "",
                    placeholder="stop only when true, e.g. user_id == 42",
                    id="breakpoint-condition",
                    compact=True,
                )
            with Horizontal():
                yield Label("log")
                yield Input(
                    value=(self.options.log_message or "") if self.options else "",
                    placeholder="print without stopping, e.g. order {order.id} received",
                    id="breakpoint-log",
                    compact=True,
                )
            yield Static(HINT, id="breakpoint-status", markup=False)

    def on_mount(self) -> None:
        self.query_one("#breakpoint-condition", Input).focus()

    @on(Input.Submitted)
    def save_breakpoint(self) -> None:
        try:
            options = breakpoint_options(
                self.query_one("#breakpoint-condition", Input).value,
                self.query_one("#breakpoint-log", Input).value,
            )
        except ValueError as error:
            status = self.query_one("#breakpoint-status", Static)
            status.update(str(error))
            status.add_class("error")
            return
        self.dismiss(("save", options))

    def action_cancel(self) -> None:
        self.dismiss(None)
