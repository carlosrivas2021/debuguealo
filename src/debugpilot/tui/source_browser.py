"""Read-only project source and session-local, unverified breakpoint intent."""

from itertools import islice
from pathlib import Path
from stat import S_ISREG

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static, TextArea, Tree


class SourceBrowser(Vertical):
    """Expand directories lazily; never write source or claim adapter verification."""

    def __init__(self):
        super().__init__(id="source-browser")
        self.root_path: Path | None = None
        self.file_path: Path | None = None
        self._marks: dict[tuple[Path, Path], set[int]] = {}
        self._loaded = set()
        self._file_node = None

    def compose(self) -> ComposeResult:
        yield Static("Select a source file. Breakpoints are pending (no debugger).",
                     id="source-status", markup=False)
        with Horizontal(id="source-content"):
            yield Tree("Files", id="source-tree")
            yield TextArea(read_only=True, show_line_numbers=True, soft_wrap=False,
                           id="source-text")
        yield Button("Toggle breakpoint at cursor (pending)",
                     id="source-breakpoint", disabled=True)

    def set_project(self, root: Path | None):
        root = root.resolve() if root is not None else None
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
        self.query_one(TextArea).load_text("")
        self.query_one(Button).disabled = True
        self.query_one(Static).update(
            "Select a source file. Breakpoints are pending (no debugger)."
        )

    def _populate(self, node):
        path, _ = node.data
        if path in self._loaded:
            return
        self._loaded.add(path)
        try:
            # Do not follow symbolic links outside the selected project (or into loops).
            if not path.resolve().is_relative_to(self.root_path):
                raise OSError("Directory is outside the selected project")
            entries = list(islice(path.iterdir(), 2001))
            if len(entries) > 2000:
                self.query_one(Static).update("Directory preview limited to 2000 entries.")
            entries = sorted(entries[:2000], key=lambda p: (not p.is_dir(), p.name.casefold()))
            for entry in entries:
                if entry.is_symlink() or entry.is_junction():
                    continue
                child = node.add(Text(entry.name), (entry, None), allow_expand=entry.is_dir())
                if entry.is_file():
                    self._show_marks(child)
        except OSError as error:
            self.query_one(Static).update(f"Unable to list {path}: {error}")

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
        self._clear_source()
        try:
            if not path.resolve().is_relative_to(self.root_path):
                raise ValueError("File is outside the selected project")
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
        except (OSError, ValueError) as error:
            self.query_one(Static).update(f"Unable to open {path}: {error}")
            return
        self.file_path = path
        self._file_node = event.node.parent if line is not None else event.node
        editor = self.query_one(TextArea)
        editor.load_text(source)
        if line is not None:
            editor.move_cursor((min(line - 1, editor.document.line_count - 1), 0))
        self.query_one(Button).disabled = False
        self.query_one(Static).update(f"{path} · Read-only · Breakpoints: pending (no debugger)")

    def breakpoints(self, root: Path, path: Path) -> tuple[int, ...]:
        return tuple(sorted(self._marks.get((root.resolve(), path.resolve()), set())))

    def _show_marks(self, node):
        path, _ = node.data
        node.remove_children()
        marks = self.breakpoints(self.root_path, path)
        node.allow_expand = bool(marks)
        for line in marks:
            node.add_leaf(Text(f"Line {line} · pending"), (path, line))
        if marks:
            node.expand()

    @on(Button.Pressed, "#source-breakpoint")
    def toggle_breakpoint(self):
        if self.file_path is None:
            return
        line = self.query_one(TextArea).cursor_location[0] + 1
        marks = self._marks.setdefault((self.root_path, self.file_path.resolve()), set())
        if line in marks:
            marks.remove(line)
        else:
            marks.add(line)
        self._show_marks(self._file_node)
