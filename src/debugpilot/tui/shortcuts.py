"""The keyboard shortcuts screen: ? lists the current area's keys, grouped by task."""

from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from debugpilot.tui.theme import theme_style

AREAS = ("containers", "code")
AREA_TITLES = {"containers": "Containers", "code": "Code"}
KEY_WIDTH = 22


@dataclass(frozen=True)
class Shortcut:
    keys: str
    action: str
    # Key names that must be bound somewhere, so the list cannot silently go stale;
    # empty for mouse gestures and keys a widget reads itself (a terminal's scroll keys).
    bindings: tuple[str, ...] = ()


EVERYWHERE = ("Everywhere", (
    Shortcut("?", "Show these shortcuts (Tab switches area)", ("question_mark",)),
    Shortcut("Ctrl+T", "Switch between Containers and Code", ("ctrl+t",)),
    Shortcut("Ctrl+O", "Edit launch.json (Ctrl+S saves, Esc closes)", ("ctrl+o", "ctrl+s")),
    Shortcut("/", "Filter the list (Enter keeps it, Esc clears it)", ("slash",)),
    Shortcut("Ctrl+← / Ctrl+→", "Move between panes (Alt+← / Alt+→ on macOS)",
             ("ctrl+left", "ctrl+right", "alt+left", "alt+right")),
    Shortcut("Mouse drag", "Copy the selected text"),
    Shortcut("Q", "Quit", ("q",)),
))

SECTIONS: dict[str, tuple[tuple[str, tuple[Shortcut, ...]], ...]] = {
    "containers": (
        ("Projects and containers", (
            Shortcut("Space", "Collapse or expand a group", ("space",)),
            Shortcut("D", "Show the selected container's details", ("d",)),
            Shortcut("R", "Preview Play / Recreate", ("r",)),
            Shortcut("Shift+R", "Preview Build + Recreate", ("shift+r",)),
            Shortcut("S", "Stop the container or project, after confirmation", ("s",)),
            Shortcut("Esc", "Cancel a Compose preview, or clear a kept filter", ("escape",)),
        )),
        ("Logs", (
            Shortcut("Ctrl+L", "Open the selected container's logs", ("ctrl+l",)),
            Shortcut("D or Esc", "Close the logs", ("d", "escape")),
            Shortcut("Ctrl+R", "Reconnect the logs", ("ctrl+r",)),
            Shortcut("Ctrl+F", "Search; N / Shift+N next / previous match", ("ctrl+f", "n", "N")),
            Shortcut("Ctrl+Space", "Pause or resume the logs", ("ctrl+space",)),
            Shortcut("Ctrl+E", "Turn auto-scroll on or off", ("ctrl+e",)),
            Shortcut("W", "Wrap long lines", ("w",)),
            Shortcut("Ctrl+Y", "Copy the selected entry", ("ctrl+y",)),
            Shortcut("Ctrl+K", "Clear the view", ("ctrl+k",)),
        )),
        ("Terminals", (
            Shortcut("C", "Open the container shell", ("c",)),
            Shortcut("H", "Open host Bash", ("h",)),
            Shortcut("O", "Show or hide the output console", ("o",)),
            Shortcut("Esc", "Leave a terminal, back to the list", ("escape",)),
            # Handled by the terminal itself, which gets every key while it has the focus.
            Shortcut("Shift+PgUp / PgDn", "Scroll back / forward (or the mouse wheel)"),
        )),
        ("AWS", (
            Shortcut("A", "Refresh the AWS credentials", ("a",)),
            Shortcut("Shift+A", "Edit the AWS config and credentials files", ("shift+a",)),
        )),
    ),
    "code": (
        ("Run and debug", (
            Shortcut("F5", "Run the profile, or Continue while paused", ("f5",)),
            Shortcut("Shift+F5", "Debug the profile", ("shift+f5",)),
            Shortcut("S", "Stop the selected run", ("s",)),
            Shortcut("R", "Restart the running profile, or reload launch.json", ("r",)),
            Shortcut("E", "Pause on uncaught exceptions → all → none", ("e",)),
            Shortcut("O", "Show or hide the terminal or debug output", ("o",)),
            Shortcut("P", "Go to the running program's input (Esc returns)", ("p",)),
            Shortcut("Shift+PgUp / PgDn", "Scroll the terminal back / forward (or the wheel)"),
        )),
        ("Stepping", (
            Shortcut("F10", "Step over", ("f10",)),
            Shortcut("F11", "Step in", ("f11",)),
            Shortcut("Shift+F11", "Step out", ("shift+f11",)),
            Shortcut("Ctrl+F10", "Run to the line under the source cursor", ("ctrl+f10",)),
        )),
        ("Breakpoints", (
            Shortcut("F9", "Toggle a breakpoint at the source cursor", ("f9",)),
            Shortcut("Shift+F9", "Add a condition, log message or hit count", ("shift+f9",)),
            Shortcut("Enter on BREAKPOINTS", "Open the list and move into it",
                     ("enter", "space")),
            Shortcut("Enter in the list", "Open the breakpoint's line", ("enter",)),
            Shortcut("Space in the list", "Switch the breakpoint off or on", ("space",)),
            Shortcut("Delete in the list", "Remove the breakpoint", ("delete",)),
            Shortcut("A in the list", "Switch all off, or all back on", ("a",)),
        )),
        ("While paused", (
            Shortcut(":", "Evaluate in the selected frame (↑↓ history, Esc returns)",
                     ("colon",)),
            Shortcut("Enter on a variable", "Change its value", ("enter",)),
            Shortcut("Space or → / ←", "Expand / collapse a variable or watch",
                     ("space", "right", "left")),
            Shortcut("C on a variable", "Copy its whole value", ("c",)),
        )),
        ("Profiles and files", (
            Shortcut("→ / ←", "Open / close a folder in the file tree", ("right", "left")),
            Shortcut("B", "Switch Git branch (type to filter the list)", ("b",)),
            Shortcut("Alt+↑ / Alt+↓", "Give the profiles or the files more rows",
                     ("alt+up", "alt+down")),
        )),
    ),
}


def shortcut_text(area: str, *, key_style: Style | str = "bold",
                  group_style: Style | str = "bold") -> Text:
    """The area's shortcuts, then the ones that work everywhere."""
    text = Text()
    for index, (group, shortcuts) in enumerate((*SECTIONS[area], EVERYWHERE)):
        if index:
            text.append("\n")
        text.append(f"{group}\n", group_style)
        for shortcut in shortcuts:
            text.append(f"  {shortcut.keys:<{KEY_WIDTH}}", key_style)
            text.append(f"{shortcut.action}\n")
    text.rstrip()
    return text


class ShortcutsScreen(ModalScreen):
    """Esc, ? or Q closes; Tab shows the other area's shortcuts."""

    DEFAULT_CSS = """
    ShortcutsScreen { align: center middle; }
    ShortcutsScreen #shortcuts {
        width: 84; max-width: 100%; height: auto; max-height: 90%;
        border: round $accent; background: $surface; padding: 0 1;
    }
    ShortcutsScreen #shortcuts-body { height: auto; max-height: 100%; }
    ShortcutsScreen #shortcuts-hint { color: $text-muted; height: 1; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("question_mark", "dismiss", show=False),
        Binding("q", "dismiss", show=False),
        Binding("tab", "switch_area", "Other area"),
    ]

    def __init__(self, area: str):
        super().__init__()
        self.area = area if area in AREAS else AREAS[0]

    def compose(self) -> ComposeResult:
        with Vertical(id="shortcuts"):
            with VerticalScroll(id="shortcuts-body"):
                yield Static(id="shortcuts-list")
            yield Static("Tab other area · Esc close", id="shortcuts-hint")

    def on_mount(self) -> None:
        self._show()
        # Its text is drawn in theme colors: a theme picked meanwhile redraws it.
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self._show())

    def _show(self) -> None:
        self.query_one("#shortcuts").border_title = f"{AREA_TITLES[self.area]} · shortcuts"
        self.query_one("#shortcuts-list", Static).update(shortcut_text(
            self.area, key_style=theme_style(self.app, "text-warning", bold=True),
            group_style=theme_style(self.app, "text-secondary", bold=True),
        ))
        self.query_one("#shortcuts-body").scroll_home(animate=False)

    def action_switch_area(self) -> None:
        self.area = AREAS[(AREAS.index(self.area) + 1) % len(AREAS)]
        self._show()

    async def action_dismiss(self, result=None) -> None:
        self.dismiss(result)
