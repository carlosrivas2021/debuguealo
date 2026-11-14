"""Source map v3 decoding and a workspace index for compiled TypeScript.

Node's Inspector reports generated JavaScript positions only. The index reads the
workspace's ``*.js.map`` files up front, so a breakpoint on a ``.ts`` line can be set on
the generated file before that file loads, and paused frames can be shown on the
``.ts`` line again. Inline ``data:`` maps and bundler index maps are not supported.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

MAX_MAP_BYTES = 8 * 1024 * 1024
MAX_MAP_FILES = 2000
# Files and folders looked at per index, so a huge tree never slows every launch.
MAX_WALK_ENTRIES = 100_000
MAP_SUFFIXES = ('.js.map', '.mjs.map', '.cjs.map')
SKIPPED_DIRECTORIES = frozenset({'node_modules', '.git', '.venv', 'venv', '__pycache__'})

_BASE64 = {character: value for value, character in enumerate(
    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/')}


def _vlq_values(segment: str) -> list[int]:
    values, value, shift = [], 0, 0
    for character in segment:
        digit = _BASE64.get(character)
        if digit is None:
            raise ValueError('Invalid character in source map mappings.')
        value += (digit & 31) << shift
        if digit & 32:
            shift += 5
            continue
        values.append(-(value >> 1) if value & 1 else value >> 1)
        value, shift = 0, 0
    if shift:
        raise ValueError('Unterminated value in source map mappings.')
    return values


def decode_mappings(mappings: str) -> list[list[tuple[int, int, int, int]]]:
    """Per generated line, (generated column, source index, original line, original column).

    Everything is 0-based. Segments that map generated code to no source are dropped.
    """
    lines = []
    source = original_line = original_column = 0
    for text in mappings.split(';'):
        column = 0
        segments = []
        for segment in filter(None, text.split(',')):
            values = _vlq_values(segment)
            if len(values) not in {1, 4, 5}:
                raise ValueError('Invalid segment in source map mappings.')
            column += values[0]
            if len(values) == 1:
                continue
            source += values[1]
            original_line += values[2]
            original_column += values[3]
            if min(column, source, original_line, original_column) < 0:
                raise ValueError('Negative position in source map mappings.')
            segments.append((column, source, original_line, original_column))
        lines.append(segments)
    return lines


@dataclass
class SourceMap:
    generated: Path
    sources: tuple[Path, ...]
    mappings: str
    _lines: list | None = field(default=None, repr=False)

    def lines(self) -> list[list[tuple[int, int, int, int]]]:
        if self._lines is None:
            self._lines = decode_mappings(self.mappings)
        return self._lines


def load_source_map(path: Path) -> SourceMap:
    """A plain v3 map whose generated file sits next to it without the .map suffix."""
    if path.stat().st_size > MAX_MAP_BYTES:
        raise ValueError('Source map is too large.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('version') != 3 or 'sections' in data
            or not isinstance(data.get('sources'), list)
            or not isinstance(data.get('mappings'), str)):
        raise ValueError('Unsupported source map.')
    root = data.get('sourceRoot') or ''
    if not isinstance(root, str):
        raise ValueError('Invalid sourceRoot.')
    sources = []
    for source in data['sources']:
        if not isinstance(source, str) or '://' in source:
            # A URL source (webpack://, http://) is not a workspace file.
            sources.append(Path(os.devnull))
            continue
        sources.append((path.parent / root / source).resolve())
    return SourceMap(path.with_name(path.name[:-len('.map')]).resolve(), tuple(sources),
                     data['mappings'])


class SourceMapIndex:
    """The workspace's source maps, by original source and by generated file."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._by_source: dict[Path, list[SourceMap]] = {}
        self._by_generated: dict[Path, SourceMap] = {}
        count = walked = 0
        for directory, names, files in os.walk(self.root):
            names[:] = sorted(name for name in names if name not in SKIPPED_DIRECTORIES)
            walked += len(names) + len(files)
            if walked > MAX_WALK_ENTRIES:
                return
            for name in sorted(files):
                if not name.endswith(MAP_SUFFIXES):
                    continue
                if count >= MAX_MAP_FILES:
                    return
                count += 1
                try:
                    source_map = load_source_map(Path(directory) / name)
                except (OSError, ValueError, UnicodeError, RecursionError):
                    continue
                self._by_generated[source_map.generated] = source_map
                for source in source_map.sources:
                    if self._inside(source):
                        self._by_source.setdefault(source, []).append(source_map)

    def _inside(self, path: Path) -> bool:
        return path.is_relative_to(self.root)

    def maps(self, source: Path) -> bool:
        """Whether some generated file maps back to this source."""
        return Path(source).resolve() in self._by_source

    def generated_position(self, source: Path, line: int) -> tuple[Path, int, int] | None:
        """(generated file, 1-based line, 0-based column) of a 1-based original line."""
        source = Path(source).resolve()
        best = None
        for source_map in self._by_source.get(source, ()):
            try:
                lines = source_map.lines()
            except ValueError:
                continue
            index = source_map.sources.index(source)
            for generated_line, segments in enumerate(lines):
                for column, source_index, original_line, _ in segments:
                    if source_index == index and original_line == line - 1:
                        candidate = (generated_line, column)
                        if best is None or candidate < best[1:]:
                            best = (source_map.generated, *candidate)
            if best is not None:
                return best[0], best[1] + 1, best[2]
        return None

    def original_position(self, generated: Path, line: int, column: int) -> tuple[Path, int] | None:
        """(original source, 1-based line) of a generated 1-based line and 0-based column."""
        source_map = self._by_generated.get(Path(generated).resolve())
        if source_map is None:
            return None
        try:
            lines = source_map.lines()
        except ValueError:
            return None
        if not 1 <= line <= len(lines) or not lines[line - 1]:
            return None
        segments = lines[line - 1]
        chosen = segments[0]
        for segment in segments:
            if segment[0] > column:
                break
            chosen = segment
        _, source_index, original_line, _ = chosen
        if source_index >= len(source_map.sources):
            return None
        source = source_map.sources[source_index]
        return (source, original_line + 1) if self._inside(source) else None
