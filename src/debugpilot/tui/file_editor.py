"""Edit one or two text files inside debugealo: Ctrl+S saves, Esc closes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static, TextArea

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.text_files import LoadedText, save_text


@dataclass
class EditableFile:
    """A file to edit; ``normalize`` validates and may rewrite the text before saving."""

    label: str
    loaded: LoadedText
    language: str | None = None
    normalize: Callable[[str], str] | None = None


class FileEditorScreen(Screen[bool]):
    """Dismisses with True when at least one file was saved, False otherwise."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "close", "Close", priority=True),
    ]
    DEFAULT_CSS = """
    FileEditorScreen { background: $background; }
    FileEditorScreen #editor-panes { height: 1fr; }
    FileEditorScreen .editor-pane { width: 1fr; height: 1fr; }
    FileEditorScreen .editor-pane.-later { border-left: solid $border-blurred; }
    FileEditorScreen .editor-title {
        height: 1; padding: 0 1; background: $panel; color: $text-secondary; text-style: bold;
    }
    FileEditorScreen TextArea { height: 1fr; border: none; background: $background; }
    FileEditorScreen #editor-status { height: 1; padding: 0 1; color: $text-muted; }
    """

    def __init__(self, files: list[EditableFile]):
        super().__init__()
        self.files = files
        self._saved_any = False
        # Texts when Esc first warned; a second Esc discards only if nothing changed since.
        self._discard_snapshot: list[str] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="editor-panes"):
            for index, file in enumerate(self.files):
                with Vertical(classes="editor-pane -later" if index else "editor-pane"):
                    yield Static("", classes="editor-title", markup=False)
                    yield TextArea(
                        file.loaded.text, language=file.language, show_line_numbers=True,
                        soft_wrap=False, tab_behavior="focus",
                    )
        yield Static("Ctrl+S save · Esc close · Tab next file", id="editor-status",
                     markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_titles()
        areas = self.query(TextArea)
        if areas:
            areas.first().focus()

    def _areas(self) -> list[TextArea]:
        return list(self.query(TextArea))

    def _modified(self) -> list[int]:
        return [index for index, (file, area) in enumerate(zip(self.files, self._areas(),
                                                               strict=True))
                if area.text != file.loaded.text]

    def _refresh_titles(self) -> None:
        titles = list(self.query(".editor-title"))
        if len(titles) != len(self.files) or len(self._areas()) != len(self.files):
            # Not every pane is mounted: the screen is still building or already closing.
            return
        modified = set(self._modified())
        for index, (file, title) in enumerate(zip(self.files, titles, strict=True)):
            state = "● " if index in modified else ""
            note = "" if file.loaded.exists else " (new file)"
            title.update(f"{state}{file.label} · {file.loaded.path}{note}")

    @on(TextArea.Changed)
    def _edited(self) -> None:
        self._refresh_titles()

    async def action_save(self) -> None:
        modified = self._modified()
        if not modified:
            self.notify("Nothing to save.", timeout=2)
            return
        areas = self._areas()
        saved = 0
        for index in modified:
            file, area = self.files[index], areas[index]
            try:
                text = file.normalize(area.text) if file.normalize else area.text
                file.loaded = await asyncio.to_thread(save_text, file.loaded, text)
            except ConfigurationError as error:
                self.notify(f"{file.label} not saved: {error}", severity="error", timeout=8)
                continue
            if area.text != text:
                # Keep the cursor where it was; formatting may move lines.
                cursor = area.cursor_location
                area.load_text(text)
                area.move_cursor(cursor)
            saved += 1
        if saved:
            self._saved_any = True
            self.notify(f"Saved {saved} file{'s' if saved != 1 else ''}", timeout=2)
        self._refresh_titles()

    def action_close(self) -> None:
        texts = [area.text for area in self._areas()]
        if self._modified() and texts != self._discard_snapshot:
            self._discard_snapshot = texts
            self.notify("Unsaved changes: Ctrl+S to save, or Esc again to discard them.",
                        severity="warning", timeout=6)
            return
        self.dismiss(self._saved_any)
