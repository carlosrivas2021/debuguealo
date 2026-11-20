"""F in Code: find a file of the project by name, or (Tab) a line by its text, and open it.

Like the branch list, it floats over a see-through screen with a filter at its top. Files
are listed once in a thread; a text search starts a moment after the last key, runs in a
thread, and gives way to the next one as you keep typing.
"""

import asyncio
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from debugpilot.storage.project_files import (
    MAX_FILES,
    matching_files,
    project_files,
    search_text,
)

FILES, TEXT = "files", "text"
MAX_SHOWN_FILES = 200
MIN_TEXT_QUERY = 2
SEARCH_DELAY = 0.2
NO_FILE = "No file matches"
NO_LINE = "No line matches"


def _count(number: int, noun: str, plural: str | None = None) -> str:
    return f"{number} {noun if number == 1 else plural or noun + 's'}"


class ProjectFinder(ModalScreen[tuple[str, int | None] | None]):
    """Dismisses with (path relative to the project, line or None), or None on Escape."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        # Priority: otherwise Tab would move the focus out of the query field.
        Binding("tab,shift+tab", "switch_mode", "Files ⇄ Text", priority=True),
    ]
    DEFAULT_CSS = """
    ProjectFinder { align: center top; }
    ProjectFinder > Vertical {
        width: 90; max-width: 95%; max-height: 85%; height: auto; margin: 2 0 0 0;
        border: round $accent; background: $surface; padding: 0 1;
    }
    ProjectFinder Label, ProjectFinder #find-status { height: auto; color: $text-muted; }
    ProjectFinder #find-modes { height: 1; margin-top: 1; }
    /* Also when focused: Input's own focus border would take the only row of text. */
    ProjectFinder Input, ProjectFinder Input:focus {
        height: 1; border: none; padding: 0 1; margin: 1 0;
        background: $boost;
    }
    ProjectFinder OptionList { height: auto; max-height: 24; border: none; }
    """

    def __init__(self, root: Path):
        super().__init__()
        self.root = Path(root)
        self.mode = FILES
        self._files: list[str] | None = None
        self._files_truncated = False
        self._targets: list[tuple[str, int | None]] = []
        self._generation = 0
        self._search_timer = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Find in {self.root.name} · Tab: Files ⇄ Text\n"
                        "Enter opens · Esc closes")
            yield Static(id="find-modes")
            yield _FindQuery(placeholder="File name", id="find-query")
            yield OptionList(id="find-results")
            yield Static("Listing files…", id="find-status", markup=False)

    def on_mount(self) -> None:
        self._show_modes()
        self.run_worker(self._list_files(), group="find-files")

    async def _list_files(self) -> None:
        self._files, self._files_truncated = await asyncio.to_thread(project_files, self.root)
        self._refresh()

    def _show_modes(self) -> None:
        active = self.app.get_css_variables().get("accent", "")
        parts = []
        for mode, name in ((FILES, "Files"), (TEXT, "Text")):
            if mode == self.mode:
                parts.append((f"[{name}]", f"bold {active}".strip()))
            else:
                parts.append((f" {name} ", "dim"))
            parts.append("  ")
        self.query_one("#find-modes", Static).update(Text.assemble(*parts[:-1]))
        self.query_one("#find-query", Input).placeholder = (
            "File name" if self.mode == FILES else "Text in the files")

    def action_switch_mode(self) -> None:
        self.mode = TEXT if self.mode == FILES else FILES
        self._show_modes()
        self._refresh()

    @on(Input.Changed, "#find-query")
    def _query_changed(self, _event: Input.Changed) -> None:
        self._refresh()

    @property
    def _query(self) -> str:
        return self.query_one("#find-query", Input).value

    def _refresh(self) -> None:
        # Any newer query ends a search still running for an older one.
        self._generation += 1
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
        if self._files is None:
            return  # Still listing; the listing refreshes when it ends.
        if self.mode == FILES:
            self._show_files()
            return
        query = self._query.strip()
        if len(query) < MIN_TEXT_QUERY:
            self._show([], None, f"Type at least {MIN_TEXT_QUERY} characters")
            return
        self._set_status("Searching…")
        generation = self._generation
        self._search_timer = self.set_timer(
            SEARCH_DELAY,
            lambda: self.run_worker(self._search(generation, query), group="find-search",
                                    exclusive=True))

    def _show_files(self) -> None:
        found = matching_files(self._query, self._files)
        total = len(self._files)
        if not self._query.strip():
            status = _count(total, "file")
        elif found:
            status = f"{len(found)} of {_count(total, 'file')}"
        else:
            status = NO_FILE
        if self._files_truncated:
            status += f" · listing stopped at {MAX_FILES:,}"
        if len(found) > MAX_SHOWN_FILES:
            status += f" · showing the first {MAX_SHOWN_FILES}"
        shown = found[:MAX_SHOWN_FILES]
        self._show([(path, None) for path in shown], [Text(path) for path in shown], status,
                   empty=NO_FILE)

    async def _search(self, generation: int, query: str) -> None:
        matches, truncated = await asyncio.to_thread(
            search_text, self.root, self._files, query,
            should_stop=lambda: generation != self._generation)
        if generation != self._generation:
            return  # A newer query took over while this one ran.
        if not matches:
            status = NO_LINE
        elif truncated:
            status = f"Showing the first {len(matches)} matches"
        else:
            status = _count(len(matches), "match", "matches")
        self._show(
            [(match.path, match.line) for match in matches],
            [Text.assemble((f"{match.path}:{match.line}", "bold"), f"  {match.text}")
             for match in matches],
            status, empty=NO_LINE)

    def _show(self, targets, prompts, status, empty=None) -> None:
        self._targets = targets
        options = self.query_one("#find-results", OptionList)
        options.clear_options()
        if prompts:
            options.add_options([Option(prompt) for prompt in prompts])
            options.highlighted = 0
        elif empty is not None:
            options.add_option(Option(empty, disabled=True))
        self._set_status(status)

    def _set_status(self, status: str) -> None:
        self.query_one("#find-status", Static).update(status)

    @on(Input.Submitted, "#find-query")
    def _open_highlighted(self, event: Input.Submitted) -> None:
        event.stop()
        index = self.query_one("#find-results", OptionList).highlighted
        if index is not None and index < len(self._targets):
            self.dismiss(self._targets[index])

    @on(OptionList.OptionSelected, "#find-results")
    def _open_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_index < len(self._targets):
            self.dismiss(self._targets[event.option_index])

    def action_close(self) -> None:
        self.dismiss(None)


class _FindQuery(Input):
    """Typing filters the results below; Up and Down move through them, Enter opens."""

    BINDINGS = [
        Binding("up", "move(-1)", show=False),
        Binding("down", "move(1)", show=False),
    ]

    def on_mount(self) -> None:
        # In its own mount, so the field is there to take the keys (as in the branch list).
        self.focus()

    def action_move(self, step: int) -> None:
        options = self.screen.query_one("#find-results", OptionList)
        if options.option_count:
            current = options.highlighted if options.highlighted is not None else -step
            options.highlighted = max(0, min(options.option_count - 1, current + step))
