import re
import struct
from collections import Counter, deque
from datetime import datetime
from typing import BinaryIO

from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import LogEntry

MAX_LINE_BYTES = 16_384


def _read_exact(reader: BinaryIO, size: int, *, eof_allowed: bool = False) -> bytes:
    result = bytearray()
    while len(result) < size:
        part = reader.read(size - len(result))
        if not part:
            if eof_allowed and not result:
                return b""
            raise DockerError("Docker returned a truncated log frame.", retryable=True)
        result.extend(part)
    return bytes(result)


def read_frames(reader: BinaryIO, *, tty: bool):
    """Decode Docker's eight-byte multiplex headers without buffering entire frames."""
    if tty:
        read = getattr(reader, "read1", reader.read)
        while data := read(MAX_LINE_BYTES):
            yield "combined", data
        return
    while header := _read_exact(reader, 8, eof_allowed=True):
        stream, size = struct.unpack(">BxxxI", header)
        if stream not in {1, 2} or size > 1_048_576 or header[1:4] != b"\0\0\0":
            raise DockerError("Docker returned an invalid or oversized log frame.")
        while size:
            data = _read_exact(reader, min(size, MAX_LINE_BYTES))
            size -= len(data)
            yield "stdout" if stream == 1 else "stderr", data


class LogDecoder:
    def __init__(self, max_line_bytes: int = MAX_LINE_BYTES):
        if not 1 <= max_line_bytes <= MAX_LINE_BYTES:
            raise ValueError("Invalid log line bound.")
        self.limit = max_line_bytes
        self._buffers: dict[str, bytes] = {}
        self._discarding: set[str] = set()

    @property
    def buffered_bytes(self) -> int:
        return sum(map(len, self._buffers.values()))

    def _entry(self, stream: str, raw: bytes, truncated: bool = False) -> LogEntry:
        text = raw.decode("utf-8", errors="replace").rstrip("\r")
        stamp, separator, body = text.partition(" ")
        timestamp = stamp if separator and re.fullmatch(r"\d{4}-\d\d-\d\dT\S+Z", stamp) else None
        if timestamp is not None:
            text = body
        severity = "unknown"
        for level, pattern in (
            ("critical", r"\b(CRITICAL|FATAL)\b"),
            ("error", r"\b(ERROR|EXCEPTION|TRACEBACK)\b"),
            ("warning", r"\b(WARN|WARNING)\b"),
            ("info", r"\bINFO\b"),
            ("debug", r"\bDEBUG\b"),
        ):
            if re.search(pattern, text, re.I):
                severity = level
                break
        return LogEntry(
            timestamp=timestamp, stream=stream, text=text, severity=severity, truncated=truncated
        )

    def feed(self, stream: str, data: bytes) -> list[LogEntry]:
        result = []
        if stream in self._discarding:
            _, newline, data = data.partition(b"\n")
            if not newline:
                return result
            self._discarding.remove(stream)
        data = self._buffers.pop(stream, b"") + data
        while data:
            line, newline, rest = data.partition(b"\n")
            if len(line) > self.limit:
                result.append(self._entry(stream, line[: self.limit], truncated=True))
                if not newline:
                    self._discarding.add(stream)
            elif newline:
                result.append(self._entry(stream, line))
            else:
                self._buffers[stream] = line
            if not newline:
                break
            data = rest
        return result

    def finish(self) -> list[LogEntry]:
        entries = [self._entry(stream, data) for stream, data in self._buffers.items() if data]
        self._buffers.clear()
        return entries


class LogBuffer:
    def __init__(self, max_entries: int = 2000, max_bytes: int = 2 * 1024 * 1024):
        if max_entries < 1 or max_bytes < 1:
            raise ValueError("Log buffer limits must be positive.")
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._entries: deque[tuple[LogEntry, int]] = deque()
        self.byte_size = 0

    def append(self, entry: LogEntry) -> None:
        size = len(entry.text.encode()) + len(entry.timestamp or "") + len(entry.stream)
        if size > self.max_bytes:
            return
        while self._entries and (
            len(self._entries) >= self.max_entries or self.byte_size + size > self.max_bytes
        ):
            _, removed = self._entries.popleft()
            self.byte_size -= removed
        self._entries.append((entry, size))
        self.byte_size += size

    def entries(self, *, text: str = "", severity: str = "") -> tuple[LogEntry, ...]:
        return tuple(
            entry
            for entry, _ in self._entries
            if text.casefold() in entry.text.casefold()
            and (not severity or entry.severity == severity)
        )

    def clear(self) -> None:
        self._entries.clear()
        self.byte_size = 0


class ReplayCursor:
    """Replay counts preserve identical legitimate messages in Docker's second-based overlap."""

    def __init__(self, capacity: int = 2000):
        self.capacity = capacity
        self.since: int | None = None
        self._seen: Counter = Counter()
        self._skip: Counter = Counter()
        self._count = 0
        self._unsafe = False
        self._latest: int | None = None
        self._replaying = False

    def reconnecting(self) -> None:
        if self._unsafe:
            raise DockerError(
                "Cannot safely resume logs: timestamp/replay limit exceeded. Restart the view."
            )
        self._skip = self._seen.copy()
        self._replaying = True

    def accept(self, entry: LogEntry) -> bool:
        try:
            second = int(datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00")).timestamp())
        except (AttributeError, ValueError, OverflowError):
            self._unsafe = True
            return True
        if self._latest is None or second > self._latest:
            self._latest = second
            # Overlap one extra second to tolerate stdout/stderr timestamp skew.
            self.since = max(1, second - 1)
            for key in tuple(self._seen):
                if key[0] < self.since:
                    self._count -= self._seen.pop(key)
                    self._skip.pop(key, None)
        if second < self.since:
            if self._replaying:
                return False
            self._unsafe = True
            return True  # Never drop initial history due to cross-channel skew.
        key = (second, entry.timestamp, entry.stream, entry.text, entry.truncated)
        if self._skip[key]:
            self._skip[key] -= 1
            return False
        self._count += 1
        if self._count > self.capacity:
            self._unsafe = True
        else:
            self._seen[key] += 1
        return True
