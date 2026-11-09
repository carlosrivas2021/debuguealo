"""In-memory Compose output: per-project transcripts and the failure display."""

from collections import OrderedDict
from collections.abc import Callable

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, RichLog, Static

from debugpilot.core.models import LogEntry
from debugpilot.docker.logs import LogBuffer


class ProjectOutputBuffers:
    """One bounded transcript per Compose project, least recently used evicted first.

    Writing to or viewing a project marks it as recently used. Beyond ``max_projects``
    the oldest buffer is dropped, except for projects ``protected`` reports as busy
    (a Compose run still writing to them).
    """

    def __init__(
        self,
        *,
        max_projects: int = 8,
        max_entries: int = 1000,
        max_bytes: int = 1024 * 1024,
        protected: Callable[[str], bool] = lambda _project: False,
    ):
        self.max_projects = max(1, max_projects)
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._protected = protected
        self._buffers: OrderedDict[str, LogBuffer] = OrderedDict()

    def get(self, project: str | None) -> LogBuffer | None:
        return self._buffers.get(project) if project else None

    def projects(self) -> tuple[str, ...]:
        return tuple(self._buffers)

    def touch(self, project: str | None) -> None:
        if project in self._buffers:
            self._buffers.move_to_end(project)

    def append(self, project: str, entry: LogEntry) -> None:
        self._use(project).append(entry)

    def reset(self, project: str) -> LogBuffer:
        """Start a new transcript for this project; other projects are untouched."""
        buffer = self._use(project)
        buffer.clear()
        return buffer

    def _use(self, project: str) -> LogBuffer:
        buffer = self._buffers.get(project)
        if buffer is None:
            buffer = LogBuffer(max_entries=self._max_entries, max_bytes=self._max_bytes)
            self._buffers[project] = buffer
        self._buffers.move_to_end(project)
        self._evict(keep=project)
        return buffer

    def _evict(self, *, keep: str) -> None:
        while len(self._buffers) > self.max_projects:
            victim = next(
                (
                    name
                    for name in self._buffers
                    if name != keep and not self._protected(name)
                ),
                None,
            )
            if victim is None:
                return
            del self._buffers[victim]


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
