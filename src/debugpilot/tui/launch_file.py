"""Edit the workspace launch file in the caller's terminal."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.launch_profiles import MAX_LAUNCH_BYTES


def open_launch_file(path: Path) -> None:
    """Wait for nano (or vi) to exit, inheriting the suspended TUI's terminal."""
    try:
        target = Path(path).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise ConfigurationError(
            "Cannot open launch.json because the file is unavailable."
        ) from None
    if not target.is_file():
        raise ConfigurationError("Cannot open launch.json because the target is not a file.")

    editor = shutil.which("nano") or shutil.which("vi")
    if editor is None:
        raise ConfigurationError("Install nano or vi on PATH to edit launch.json in this terminal.")
    try:
        # No timeout or redirected streams: the editor owns the terminal until exit.
        result = subprocess.run([editor, str(target)], shell=False, check=False)
    except OSError:
        raise ConfigurationError(f"Could not start the terminal editor for {target}.") from None
    if result.returncode != 0:
        raise ConfigurationError(
            f"The terminal editor exited with status {result.returncode}; "
            "check launch.json before retrying."
        )
    _format_launch_json(target)


def _file_signature(path: Path) -> tuple[int, int, int, int, int]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError("Cannot format launch.json because the target is not a file.")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


class _DuplicateObjectKey(Exception):
    pass


class _NonstandardNumber(Exception):
    def __init__(self, token: str) -> None:
        self.token = token


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateObjectKey
        result[key] = value
    return result


def _reject_nonstandard_number(token: str) -> None:
    raise _NonstandardNumber(token)


def _iter_json_tokens(text: str) -> Iterator[tuple[str, int]]:
    """Yield original tokens and offsets without scanning ahead of the caller."""
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
        elif char == '"':
            _value, end = json.decoder.scanstring(text, index + 1, True)
            yield text[index:end], index
            index = end
        elif char in "{}[]:,":
            yield char, index
            index += 1
        else:
            end = index + 1
            while end < len(text) and not text[end].isspace() and text[end] not in '{}[]:,"':
                end += 1
            yield text[index:end], index
            index = end


def _json_tokens(text: str) -> list[str]:
    """Split validated JSON into original lexical tokens, retaining their spelling."""
    return [token for token, _position in _iter_json_tokens(text)]


def _pretty_json_tokens(tokens: list[str]) -> str:
    output: list[str] = []
    depth = 0
    for index, token in enumerate(tokens):
        previous = tokens[index - 1] if index else ""
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token in ("{", "["):
            output.append(token)
            depth += 1
            if following != ("}" if token == "{" else "]"):
                output.append("\n" + "  " * depth)
        elif token in ("}", "]"):
            depth -= 1
            if previous not in ("{", "["):
                output.append("\n" + "  " * depth)
            output.append(token)
        elif token == ",":
            output.append(",\n" + "  " * depth)
        elif token == ":":
            output.append(": ")
        else:
            output.append(token)
    return "".join(output) + "\n"


def _format_launch_json(target: Path) -> None:
    """Format valid editor output after checking for concurrent newer saves."""
    try:
        before = _file_signature(target)
        original = target.read_bytes()
        after_read = _file_signature(target)
        if before != after_read:
            raise ConfigurationError(
                "launch.json changed while being read; newer contents were left untouched."
            )
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError as error:
            prefix = original[: error.start].decode("utf-8", errors="replace")
            line = prefix.count("\n") + 1
            column = len(prefix.rsplit("\n", 1)[-1]) + 1
            raise ConfigurationError(
                f"Invalid JSON in launch.json at line {line}, column {column}."
            ) from None

        try:
            json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_nonstandard_number,
            )
        except _DuplicateObjectKey:
            raise ConfigurationError(
                "Invalid JSON in launch.json at line 1, column 1 (duplicate object key)."
            ) from None
        except _NonstandardNumber as error:
            for token, position in _iter_json_tokens(text):
                if token.startswith(error.token):
                    line = text.count("\n", 0, position) + 1
                    column = position - text.rfind("\n", 0, position)
                    break
            else:
                line, column = 1, 1
            raise ConfigurationError(
                f"Invalid JSON in launch.json at line {line}, column {column}."
            ) from None
        except json.JSONDecodeError as error:
            raise ConfigurationError(
                f"Invalid JSON in launch.json at line {error.lineno}, column {error.colno}."
            ) from None

        formatted = _pretty_json_tokens(_json_tokens(text)).encode("utf-8")
        if len(formatted) > MAX_LAUNCH_BYTES:
            raise ConfigurationError(
                "Formatted launch.json exceeds the 256 KiB limit; "
                "the original file was left unchanged."
            )
        if formatted == original:
            return

        mode = stat.S_IMODE(target.stat().st_mode)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            stream = os.fdopen(descriptor, "wb")
            descriptor = -1
            with stream:
                stream.write(formatted)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            if _file_signature(target) != after_read or target.read_bytes() != original:
                raise ConfigurationError(
                    "launch.json changed while it was being formatted; "
                    "the newer contents were left untouched."
                )
            os.replace(temporary, target)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary.exists():
                temporary.unlink()
    except ConfigurationError:
        raise
    except OSError:
        raise ConfigurationError(
            "Could not safely format launch.json after the editor closed."
        ) from None
