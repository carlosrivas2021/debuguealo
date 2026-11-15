"""A k9s-style filter field for a list: / opens it, Enter keeps the filter, Esc clears it."""

from textual.binding import Binding
from textual.widgets import Input


def matches(query: str, text: str) -> bool:
    """Whether text contains the query, ignoring case."""
    return query.casefold() in text.casefold()


class ListFilter(Input):
    """Filters the list ``target`` names while typing; hidden until opened."""

    BINDINGS = [Binding("escape", "clear_filter", "Clear filter", show=False)]

    def __init__(self, target: str, *, id: str):
        super().__init__(
            placeholder="Filter · Enter keeps it · Esc clears", id=id, compact=True,
        )
        self._target = target
        self.display = False

    def open(self) -> None:
        self.display = True
        self.focus()

    def _on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input is self:
            event.stop()
            # An empty filter has nothing to keep on screen.
            self.display = bool(self.value)
            self.screen.query_one(self._target).focus()

    def action_clear_filter(self) -> None:
        self.value = ""
        self.display = False
        self.screen.query_one(self._target).focus()
