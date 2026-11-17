"""A list of local Git branches to switch to, opened from the branch in the Code bar."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class BranchPicker(ModalScreen[str | None]):
    """Dismisses with the chosen branch name, or None when closed with Escape."""

    BINDINGS = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    BranchPicker { align: right top; background: $background 60%; }
    BranchPicker > Vertical {
        width: 48; max-height: 80%; height: auto; margin: 1 2 0 0;
        border: round $accent; background: $surface; padding: 0 1;
    }
    BranchPicker Label { height: 1; color: $text-muted; }
    BranchPicker OptionList { height: auto; max-height: 20; border: none; }
    """

    def __init__(self, branches: list[str], current: str | None):
        super().__init__()
        self.branches = branches
        self.current = current

    def compose(self) -> ComposeResult:
        initial = self.branches.index(self.current) if self.current in self.branches else None
        with Vertical():
            yield Label("Switch branch · Enter to switch, Esc to close")
            yield _BranchOptions(*(
                Option(f"{'●' if name == self.current else ' '} {name}", id=name)
                for name in self.branches
            ), initial=initial, id="branch-options")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_close(self) -> None:
        self.dismiss(None)


class _BranchOptions(OptionList):
    """The branch list picks the current branch and takes the focus once it is mounted.

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
        self.focus()
