"""In-memory display for failed inline Compose operations."""

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, RichLog, Static


class ComposeOutputScreen(ModalScreen):
    """Show bounded Compose output and, only when eligible, request pull consent."""

    BINDINGS = [Binding("escape", "close", "Close")]
    DEFAULT_CSS = """
    ComposeOutputScreen { align: center middle; background: $background 80%; }
    ComposeOutputScreen > VerticalScroll {
        width: 95%; max-width: 110; height: 90%; border: round $accent;
        background: $surface; padding: 0 1;
    }
    ComposeOutputScreen Static { height: auto; }
    ComposeOutputScreen RichLog { height: 1fr; min-height: 6; }
    ComposeOutputScreen Horizontal { height: 3; }
    ComposeOutputScreen Button { width: 1fr; min-width: 12; }
    """

    def __init__(
        self,
        *,
        project: str,
        scope: str,
        action: str,
        exit_code: int,
        output: str,
        allow_download: bool,
        retry: bool = False,
    ):
        super().__init__()
        self.project = project
        self.scope = scope
        self.action = action
        self.exit_code = exit_code
        self.output = output
        self.allow_download = allow_download
        self.retry = retry

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(
                f"Compose {'retry ' if self.retry else ''}exited {self.exit_code}",
                id="compose-output-status",
                markup=False,
            )
            yield Static(
                f"Project: {self.project} · Scope: {self.scope} · Action: {self.action}",
                id="compose-output-scope",
                markup=False,
            )
            if self.allow_download:
                yield Static(
                    "This profile is missing an image. Download missing images and retry the "
                    f"same {self.action} action for {self.project} / {self.scope}?",
                    id="compose-download-question",
                    markup=False,
                )
            yield RichLog(id="compose-failure-output", wrap=True, min_width=1, markup=False)
            with Horizontal():
                if self.allow_download:
                    yield Button("Download and retry", id="compose-download", variant="warning")
                yield Button(
                    "Close" if not self.allow_download else "Cancel", id="compose-output-close"
                )

    def on_mount(self) -> None:
        output = self.query_one("#compose-failure-output", RichLog)
        output.write(
            Text(self.output)
            if self.output
            else Text("No output was retained. Review the exit status and Docker state.")
        )
        self.query_one("#compose-output-close", Button).focus()

    @on(Button.Pressed, "#compose-download")
    def download(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#compose-output-close")
    def close(self) -> None:
        self.dismiss(False)

    def action_close(self) -> None:
        self.dismiss(False)
