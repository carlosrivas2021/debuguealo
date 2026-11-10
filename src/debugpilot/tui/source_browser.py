"""Read-only project source, requested breakpoints and separate adapter feedback."""

from itertools import islice
from pathlib import Path
from stat import S_ISREG

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.strip import Strip
from textual.widgets import Button, Static, TextArea, Tree

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.breakpoints import BreakpointOptions, BreakpointStore
from debugpilot.tui.breakpoint_dialog import BreakpointDialog

# Dark yellow keeps syntax colors readable while marking the paused line.
EXECUTION_LINE_STYLE = Style(bgcolor="#6b5d00")
HINT_STYLE = Style(color="#6b7780", italic=True)
HINT_GAP = 4
SOURCE_HINT = (
    "Select a file. F9 or click the gutter to toggle a breakpoint; "
    "Shift+F9 adds a condition or log message."
)
BREAKPOINT_GLYPHS = {
    "plain": ("●", Style(color="#ef4444", bold=True)),
    "condition": ("◆", Style(color="#ef4444", bold=True)),
    "log": ("◇", Style(color="#38bdf8", bold=True)),
}
MAX_LABEL_TEXT = 40


def breakpoint_kind(options: BreakpointOptions | None) -> str:
    """A log message makes a logpoint even with a condition: it never stops."""
    if options is not None and options.log_message:
        return "log"
    if options is not None and options.condition:
        return "condition"
    return "plain"


def _breakpoint_hint(options: BreakpointOptions | None) -> str:
    parts = []
    if options is not None and options.condition:
        parts.append(f"if {' '.join(options.condition.split())}")
    if options is not None and options.log_message:
        parts.append(f"log: {' '.join(options.log_message.split())}")
    return " · ".join(parts)


def _shorten(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_LABEL_TEXT else text[:MAX_LABEL_TEXT - 1] + "…"


def _overlay(strip: Strip, style: Style) -> Strip:
    # Post-style wins over TextArea's own cursor-line and base backgrounds.
    return Strip(Segment.apply_style(strip, post_style=style), strip.cell_length)


class SourceText(TextArea):
    """Read-only source with clickable pending breakpoint dots in the line gutter."""

    class BreakpointClicked(Message):
        def __init__(self, line: int):
            super().__init__()
            self.line = line

    def __init__(self, **kwargs):
        super().__init__(read_only=True, show_line_numbers=True, soft_wrap=False, **kwargs)
        self.breakpoint_lines: tuple[int, ...] = ()
        # Lines with a condition or log message; others draw the plain dot.
        self.breakpoint_kinds: dict[int, str] = {}
        # Dim text drawn after a line's code: its condition and/or log message.
        self.breakpoint_hints: dict[int, str] = {}
        self.execution_line: int | None = None

    def _with_hint(self, strip: Strip, line: int) -> Strip:
        hint = self.breakpoint_hints.get(line)
        if not hint or line > self.document.line_count:
            return strip
        code = self.document.get_line(line - 1).expandtabs(self.indent_width).rstrip()
        start = self.gutter_width + cell_len(code) + HINT_GAP - self.scroll_offset.x
        room = strip.cell_length - start
        # Only where the code leaves room; otherwise the panel below has the detail.
        if start < self.gutter_width + HINT_GAP or room < min(cell_len(hint), 12):
            return strip
        if cell_len(hint) > room:
            hint = hint[:room - 1] + "…"
        background = next(iter(strip.crop(start, start + 1)), None)
        base = background.style if background is not None and background.style else Style()
        return Strip.join([
            strip.crop(0, start),
            Strip([Segment(hint, base + HINT_STYLE)], cell_len(hint)),
            strip.crop(start + cell_len(hint)),
        ])

    def render_line(self, y: int) -> Strip:
        line = y + self.scroll_offset.y + 1
        strip = self._with_hint(super().render_line(y), line)
        if line == self.execution_line:
            gutter = self.gutter_width
            strip = Strip.join([
                Strip([Segment("▶", Style(color="#facc15", bold=True))], 1),
                strip.crop(1, gutter),
                _overlay(strip.crop(gutter), EXECUTION_LINE_STYLE),
            ])
        if line not in self.breakpoint_lines:
            return strip
        # Use the gutter's existing margin, preserving line numbers and source geometry.
        column = self.gutter_width - 2
        mark, style = BREAKPOINT_GLYPHS[self.breakpoint_kinds.get(line, "plain")]
        return Strip.join([
            strip.crop(0, column),
            Strip([Segment(mark, style)], 1),
            strip.crop(column + 1),
        ])

    def on_click(self, event: Click):
        offset = event.get_content_offset(self)
        if event.button != 1 or offset is None or offset.x != self.gutter_width - 2:
            return
        line = offset.y + self.scroll_offset.y + 1
        if 1 <= line <= self.document.line_count:
            self.post_message(self.BreakpointClicked(line))
            event.stop()


class SourceBrowser(Vertical):
    """Expand files lazily; keep source intent independent of adapter verification."""

    class BreakpointsChanged(Message):
        def __init__(self, root, path, lines, options=None):
            super().__init__()
            self.root, self.path, self.lines = root, path, lines
            # Line -> BreakpointOptions for the lines that have a condition or log message.
            self.options = dict(options or {})

    # Structural layout lives with the widget so it renders correctly without the app sheet.
    DEFAULT_CSS = """
    SourceBrowser #source-layout { height: 1fr; }
    SourceBrowser #source-sidebar { width: 30; min-width: 22; }
    SourceBrowser #source-tree { height: 1fr; }
    SourceBrowser #source-main { width: 1fr; }
    SourceBrowser #source-editor-row { height: 2fr; min-height: 6; }
    SourceBrowser #source-pane { width: 1fr; }
    SourceBrowser #source-header { height: auto; }
    SourceBrowser #source-status { width: 1fr; height: auto; }
    SourceBrowser #source-breakpoint { width: auto; }
    SourceBrowser #source-text { height: 1fr; }
    SourceBrowser #breakpoint-info {
        height: auto; border: round $accent; background: $surface; padding: 0 1;
    }
    """

    def __init__(self, *, sidebar_header=None, editor_side=None, bottom=None):
        super().__init__(id="source-browser")
        # Optional slots let a host place its own panes around the source in an IDE layout
        # while the tree and editor stay owned by this widget.
        self._sidebar_header = sidebar_header
        self._editor_side = editor_side
        self._bottom = bottom
        self.root_path: Path | None = None
        self.file_path: Path | None = None
        self.breakpoint_store = BreakpointStore()
        self._persistence_error = None
        try:
            self._marks: dict[tuple[Path, Path], set[int]] = {
                key: set(lines) for key, lines in self.breakpoint_store.load().items()
            }
            self._options: dict[tuple[Path, Path], dict[int, BreakpointOptions]] = {
                key: dict(options)
                for key, options in self.breakpoint_store.load_options().items()
            }
        except ConfigurationError as error:
            self._marks = {}
            self._options = {}
            self._persistence_error = str(error)
        self._loaded = set()
        self._file_node = None
        self._verification = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="source-layout"):
            with Vertical(id="source-sidebar"):
                if self._sidebar_header is not None:
                    yield self._sidebar_header
                yield Static("FILES", id="source-files-title", classes="pane-title")
                yield Tree("Files", id="source-tree")
            with Vertical(id="source-main"):
                with Horizontal(id="source-editor-row"):
                    with Vertical(id="source-pane"):
                        with Horizontal(id="source-header"):
                            yield Static(SOURCE_HINT, id="source-status", markup=False)
                            yield Button("● Breakpoint", id="source-breakpoint", disabled=True)
                        yield SourceText(id="source-text")
                        info = Static("", id="breakpoint-info", markup=False)
                        info.display = False
                        yield info
                    if self._editor_side is not None:
                        yield self._editor_side
                if self._bottom is not None:
                    yield self._bottom

    def set_project(self, root: Path | None):
        root = Path(root).absolute() if root is not None else None
        if root == self.root_path:
            return
        self.root_path = root
        self._loaded.clear()
        self._clear_source()
        tree = self.query_one(Tree)
        tree.clear()
        tree.root.data = (root, None)
        tree.root.set_label(Text(root.name if root else "Files"))
        tree.root.expand()
        if root is not None:
            self._populate(tree.root)

    def _clear_source(self):
        self.file_path = None
        self._file_node = None
        editor = self.query_one(SourceText)
        editor.breakpoint_lines = ()
        editor.breakpoint_kinds = {}
        editor.breakpoint_hints = {}
        editor.execution_line = None
        editor.load_text("")
        self.query_one("#source-breakpoint", Button).disabled = True
        self._set_status(SOURCE_HINT)

    def _populate(self, node):
        path, _ = node.data
        if path in self._loaded:
            return
        self._loaded.add(path)
        try:
            # Do not follow symbolic links outside the selected project (or into loops).
            self._safe_path(path)
            entries = list(islice(path.iterdir(), 2001))
            if len(entries) > 2000:
                self.query_one("#source-status", Static).update(
                    "Directory preview limited to 2000 entries."
                )
            entries = sorted(entries[:2000], key=lambda p: (not p.is_dir(), p.name.casefold()))
            for entry in entries:
                if entry.is_symlink() or entry.is_junction():
                    continue
                child = node.add(Text(entry.name), (entry, None), allow_expand=entry.is_dir())
                if entry.is_file():
                    self._show_marks(child)
        except (OSError, ValueError, RuntimeError) as error:
            self._set_status(f"Unable to list {path}: {error}")

    @on(Tree.NodeExpanded, "#source-tree")
    def expand_directory(self, event):
        if event.node.data:
            path, line = event.node.data
            if path is not None and line is None and path.is_dir():
                self._populate(event.node)

    @on(Tree.NodeSelected, "#source-tree")
    def select_source(self, event):
        if not event.node.data:
            return
        path, line = event.node.data
        if path is None or path.is_dir():
            return
        self.open_source(self.root_path, path, line, node=event.node)

    def _safe_path(self, path):
        path = Path(path).absolute()
        root = self.root_path
        if root is None or not path.resolve().is_relative_to(root):
            raise ValueError("File is outside the selected project")
        # Check every component, including replaced parent directories and the root.
        for component in (path, *path.parents, root, *root.parents):
            if component.is_symlink() or component.is_junction():
                raise ValueError("Source paths cannot contain links or junctions")
        return path

    def open_source(self, root, path, line=None, *, node=None):
        """Preview a debugger or tree path through the same bounded read-only checks."""
        self.set_project(root)
        self._clear_source()
        path = Path(path)
        if not path.is_absolute():
            path = self.root_path / path
        try:
            path = self._safe_path(path)
            info = path.stat()
            if not S_ISREG(info.st_mode):
                raise ValueError("Only regular source files can be previewed")
            if info.st_size > 1024 * 1024:
                raise ValueError("Source preview limit is 1 MiB")
            with path.open("rb") as stream:
                data = stream.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError("Source preview limit is 1 MiB")
            if b"\x00" in data:
                raise ValueError("Binary files cannot be previewed")
            source = data.decode("utf-8-sig")
        except (OSError, ValueError, RuntimeError) as error:
            self._set_status(f"Unable to open {path}: {error}")
            return False
        self.file_path = path.resolve()
        self._file_node = node.parent if node is not None and line is not None else node
        if self._file_node is None:
            current = self.query_one(Tree).root
            for part in self.file_path.relative_to(self.root_path).parts:
                self._populate(current)
                current = next((n for n in current.children if n.data[0].name == part), None)
                if current is None:
                    break
            self._file_node = current
        editor = self.query_one(TextArea)
        editor.load_text(source)
        self._refresh_editor_marks()
        if line is not None:
            editor.move_cursor((min(line - 1, editor.document.line_count - 1), 0))
        self.query_one("#source-breakpoint", Button).disabled = False
        self._set_status(f"{path.name} · read-only")
        return True

    def show_execution(self, root, path, line):
        if self.open_source(root, path, line):
            editor = self.query_one(SourceText)
            editor.execution_line = line
            editor.refresh()

    def clear_execution(self):
        if not self.query(SourceText):
            return
        editor = self.query_one(SourceText)
        editor.execution_line = None
        editor.refresh()

    def options_snapshot(self, root):
        """Detached root-scoped options of marked lines, keyed like breakpoint_snapshot."""
        root = Path(root).resolve()
        return {
            str(path): {line: option for line, option in options.items()
                        if line in self._marks.get((owner, path), set())}
            for (owner, path), options in self._options.items()
            if owner == root and options and self._marks.get((owner, path))
        }

    def breakpoint_options(self, root: Path, path: Path) -> dict[int, BreakpointOptions]:
        return dict(self._options.get((root.resolve(), path.resolve()), {}))

    def breakpoint_snapshot(self, root):
        """Detached root-scoped requested intent; adapter responses never modify it."""
        root = Path(root).resolve()
        return {str(path): tuple(sorted(lines)) for (owner, path), lines in self._marks.items()
                if owner == root and lines}

    def set_verification(self, root, responses, requested=None):
        root = Path(root).resolve()
        self._verification = {key: value for key, value in self._verification.items()
                              if key[0] != root}
        for path, entries in responses.items():
            lines = (requested.get(str(path), ()) if requested is not None
                     else self.breakpoints(root, Path(path)))
            for line, response in zip(lines, entries, strict=False):
                state = "verified" if response.get("verified") else "unverified"
                actual = response.get("line", line)
                if actual != line:
                    state += f" → Line {actual}"
                self._verification[(root, Path(path).resolve(), line)] = state
        if self.root_path == root and self.query(Tree):
            def refresh_node(node):
                path, line = node.data
                if line is None and path is not None and not path.is_dir():
                    self._show_marks(node)
                else:
                    for child in list(node.children):
                        refresh_node(child)
            refresh_node(self.query_one(Tree).root)

    def breakpoints(self, root: Path, path: Path) -> tuple[int, ...]:
        return tuple(sorted(self._marks.get((root.resolve(), path.resolve()), set())))

    def _show_marks(self, node):
        if node is None:
            return
        path, _ = node.data
        node.remove_children()
        marks = self.breakpoints(self.root_path, path)
        options = self.breakpoint_options(self.root_path, path)
        node.allow_expand = bool(marks)
        for line in marks:
            state = self._verification.get((self.root_path, path.resolve(), line), "pending")
            option = options.get(line)
            detail = ""
            if option is not None and option.condition:
                detail += f" · if {_shorten(option.condition)}"
            if option is not None and option.log_message:
                detail += f" · log: {_shorten(option.log_message)}"
            node.add_leaf(Text(f"Line {line}{detail} · {state}"), (path, line))
        if marks:
            node.expand()

    @on(SourceText.BreakpointClicked)
    def gutter_breakpoint(self, event):
        if self.file_path is not None:
            self.query_one(TextArea).move_cursor((event.line - 1, 0))
            self.toggle_breakpoint()

    @on(Button.Pressed, "#source-breakpoint")
    def toggle_breakpoint(self):
        if self.file_path is None:
            return
        line = self.query_one(TextArea).cursor_location[0] + 1
        key = (self.root_path, self.file_path.resolve())
        # Removing a breakpoint also removes its condition and log message.
        self._apply_breakpoint(key, line, line not in self._marks.get(key, set()), None)

    def edit_breakpoint(self):
        """Shift+F9: edit the condition and log message of the line at the cursor."""
        if self.file_path is None:
            return
        editor = self.query_one(TextArea)
        line = editor.cursor_location[0] + 1
        key = (self.root_path, self.file_path.resolve())

        def done(result):
            if result is not None:
                _, options = result
                self._apply_breakpoint(key, line, True, options)

        self.app.push_screen(BreakpointDialog(
            f"{self.file_path.name}:{line}", editor.document.get_line(line - 1),
            self._options.get(key, {}).get(line),
        ), done)

    def _apply_breakpoint(self, key, line, present, options):
        marks = self._marks.setdefault(key, set())
        line_options = self._options.setdefault(key, {})
        if present:
            marks.add(line)
        else:
            marks.discard(line)
        if present and options is not None:
            line_options[line] = options
        else:
            line_options.pop(line, None)
        if not line_options:
            self._options.pop(key, None)
        self._verification.pop((key[0], key[1], line), None)
        if self.file_path is not None and self.file_path.resolve() == key[1]:
            self._show_marks(self._file_node)
            self._refresh_editor_marks()
        try:
            # Always save marks and options together: saving marks alone drops options.
            self.breakpoint_store.save(self._marks, self._options)
            self._persistence_error = None
        except ConfigurationError as error:
            self._persistence_error = str(error)
        if self.file_path is not None:
            self._set_status(f"{self.file_path.name} · read-only")
        self.post_message(self.BreakpointsChanged(
            key[0], key[1], tuple(sorted(marks)), self._options.get(key, {})
        ))

    @on(TextArea.SelectionChanged, "#source-text")
    def _cursor_moved(self, _event):
        self._refresh_breakpoint_info()

    def _refresh_breakpoint_info(self):
        """Show the cursor line's condition and log message, read-only, below the source."""
        if not self.query("#breakpoint-info"):
            return
        panel = self.query_one("#breakpoint-info", Static)
        option = None
        if self.file_path is not None:
            line = self.query_one(SourceText).cursor_location[0] + 1
            key = (self.root_path, self.file_path.resolve())
            if line in self._marks.get(key, set()):
                option = self._options.get(key, {}).get(line)
        if breakpoint_kind(option) == "plain":
            panel.display = False
            return
        muted = "#7f8c93"
        text = Text()
        if option.condition:
            # A logpoint never stops, so its condition only decides whether it prints.
            meaning = "only when true" if option.log_message else "stops only when true"
            text.append("if   ", style=muted)
            text.append(option.condition)
            text.append(f"   {meaning}", style=muted)
        if option.log_message:
            if text:
                text.append("\n")
            text.append("log  ", style=muted)
            text.append(option.log_message)
            text.append("   prints without stopping", style=muted)
        text.append("\nShift+F9 edit · F9 remove", style=muted)
        kind = "logpoint" if option.log_message else "conditional breakpoint"
        panel.border_title = f"{self.file_path.name}:{line} · {kind}"
        panel.update(text)
        panel.display = True

    def _refresh_editor_marks(self):
        editor = self.query_one(SourceText)
        if self.file_path is None:
            editor.breakpoint_lines = ()
            editor.breakpoint_kinds = {}
            editor.breakpoint_hints = {}
        else:
            editor.breakpoint_lines = self.breakpoints(self.root_path, self.file_path)
            editor.breakpoint_kinds = {
                line: kind
                for line, option in self.breakpoint_options(self.root_path, self.file_path).items()
                if (kind := breakpoint_kind(option)) != "plain"
            }
            editor.breakpoint_hints = {
                line: hint
                for line, option in self.breakpoint_options(self.root_path, self.file_path).items()
                if (hint := _breakpoint_hint(option))
            }
        editor.refresh()
        self._refresh_breakpoint_info()

    def _set_status(self, message):
        if self._persistence_error:
            message = f"{message} · {self._persistence_error}"
        self.query_one("#source-status", Static).update(message)
