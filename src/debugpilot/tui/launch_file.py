"""Validate and format launch.json text for the in-app editor."""

from __future__ import annotations

import json
from collections.abc import Iterator

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.launch_profiles import MAX_LAUNCH_BYTES


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


def format_launch_text(text: str) -> str:
    """Validate launch.json text and return it formatted, keeping key order and spelling.

    Errors name only the line and column, never the content.
    """
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
    formatted = _pretty_json_tokens(_json_tokens(text))
    if len(formatted.encode("utf-8")) > MAX_LAUNCH_BYTES:
        raise ConfigurationError(
            "Formatted launch.json exceeds the 256 KiB limit; the file was left unchanged."
        )
    return formatted


