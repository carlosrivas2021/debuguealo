"""A list of local Git branches to switch to, opened with B or from the branch in the Code bar.

It drops down under the branch over a see-through screen, so the workspace stays in view,
and a filter at its top narrows the list as you type.
"""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

NO_MATCH = "No branch matches"


def _in_order(query: str, name: str) -> bool:
    """Whether every letter of the query appears in the name, in order."""
    position = 0
    for letter in query:
        position = name.find(letter, position) + 1
        if not position:
            return False
    return True


def matching_branches(query: str, branches: list[str]) -> list[str]:
    """Branches that look like the query: starting with it, then containing it, then
    holding its letters in order (`flog` finds `feature/login`); the list order breaks ties.
    """
    query = query.strip().casefold()
    if not query:
        return list(branches)
    ranked = []
    for index, name in enumerate(branches):
        folded = name.casefold()
        if folded.startswith(query):
            rank = 0
        elif query in folded:
            rank = 1
        elif _in_order(query, folded):
            rank = 2
        else:
            continue
        ranked.append((rank, index, name))
    return [name for _rank, _index, name in sorted(ranked)]


class BranchPicker(ModalScreen[str | None]):
    """Dismisses with the chosen branch name, or None when closed with Escape."""

    BINDINGS = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    BranchPicker { align: right top; background: transparent; }
    BranchPicker > Vertical {
        width: 48; max-height: 80%; height: auto; margin: 1 2 0 0;
        border: round $accent; background: $surface; padding: 0 1;
    }
    BranchPicker Label { height: 1; color: $text-muted; }
    BranchPicker Input { height: 1; border: none; padding: 0; margin-bottom: 1; }
    BranchPicker OptionList { height: auto; max-height: 20; border: none; }
    """

    def __init__(self, branches: list[str], current: str | None):
        super().__init__()
        self.branches = branches
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Switch branch · type to filter · Enter switches · Esc closes")
            yield _BranchFilter(placeholder="Filter branches", id="branch-filter")
            yield _BranchOptions(
                *self._options(self.branches), initial=self._current_index(self.branches),
                id="branch-options")

    def _options(self, names: list[str]) -> list[Option]:
        if not names:
            return [Option(NO_MATCH, disabled=True)]
        return [Option(f"{'●' if name == self.current else ' '} {name}", id=name)
                for name in names]

    def _current_index(self, names: list[str]) -> int | None:
        return names.index(self.current) if self.current in names else None

    @on(Input.Changed, "#branch-filter")
    def _filter(self, event: Input.Changed) -> None:
        names = matching_branches(event.value, self.branches)
        options = self.query_one(_BranchOptions)
        options.clear_options()
        options.add_options(self._options(names))
        if names:
            # With no filter the current branch stays picked; otherwise the best match.
            filtering = bool(event.value.strip())
            options.highlighted = 0 if filtering else (self._current_index(names) or 0)

    @on(Input.Submitted, "#branch-filter")
    def _choose_highlighted(self, event: Input.Submitted) -> None:
        event.stop()
        options = self.query_one(_BranchOptions)
        if options.highlighted is None:
            return
        option = options.get_option_at_index(options.highlighted)
        if not option.disabled:
            self.dismiss(option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_close(self) -> None:
        self.dismiss(None)


class _BranchFilter(Input):
    """Typing filters the list below; Up and Down move through it, Enter switches."""

    BINDINGS = [
        Binding("up", "move(-1)", show=False),
        Binding("down", "move(1)", show=False),
    ]

    def on_mount(self) -> None:
        # In its own mount, so the field is there to take the keys (see _BranchOptions).
        self.focus()

    def action_move(self, step: int) -> None:
        options = self.screen.query_one(_BranchOptions)
        if options.option_count:
            current = options.highlighted if options.highlighted is not None else -step
            options.highlighted = max(0, min(options.option_count - 1, current + step))


class _BranchOptions(OptionList):
    """The branch list picks the current branch once it is mounted.

    The picker's own on_mount can run before this list is mounted (seen on Windows), where
    querying it failed and a highlight set early was replaced by the list's own setup.
    """

    def __init__(self, *options, initial: int | None, **kwargs):
        super().__init__(*options, **kwargs)
        self._initial = initial

    def on_mount(self) -> None:
        super().on_mount()
        if self._initial is not None:
            self.highlighted = self._initial
