"""Pure validation and application of launch-profile service overrides.

This module does not load files, invoke Compose, or interpolate environment values.
"""

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

_SERVICE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z", re.ASCII)


@dataclass(frozen=True, repr=False)
class _ValidatedServiceOverrides:
    """Detached immutable override data with value-safe string representations."""

    services: tuple = field(repr=False)

    def __repr__(self):
        return "<ValidatedServiceOverrides>"

    __str__ = __repr__


def _valid_text(value):
    if "\x00" in value:
        return False
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        return False
    return True


def validate_service_overrides(overrides):
    """Validate an optional ``{"services": ...}`` payload into private immutable data.

    Only per-service ``environment`` string mappings and ``ports`` string lists are
    accepted. Environment values remain literal (including dollar signs). Errors
    intentionally contain no payload values.
    """
    if isinstance(overrides, _ValidatedServiceOverrides):
        return overrides
    if overrides is None or (isinstance(overrides, Mapping) and not overrides):
        return _ValidatedServiceOverrides(())
    if not isinstance(overrides, Mapping) or set(overrides) != {"services"}:
        raise ValueError("Invalid service overrides.")
    services = overrides["services"]
    if not isinstance(services, Mapping):
        raise ValueError("Invalid service overrides.")

    validated = []
    for name, config in services.items():
        if (
            not isinstance(name, str)
            or not _SERVICE_NAME.fullmatch(name)
            or not isinstance(config, Mapping)
            or any(key not in {"environment", "ports"} for key in config)
        ):
            raise ValueError("Invalid service overrides.")
        environment = None
        if "environment" in config:
            entries = config["environment"]
            if not isinstance(entries, Mapping):
                raise ValueError("Invalid service overrides.")
            environment = []
            for key, value in entries.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or "=" in key
                    or not _valid_text(key)
                    or not isinstance(value, str)
                    or not _valid_text(value)
                ):
                    raise ValueError("Invalid service overrides.")
                environment.append((key, value))
            environment = tuple(environment)
        ports = None
        if "ports" in config:
            values = config["ports"]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value or not _valid_text(value)
                for value in values
            ):
                raise ValueError("Invalid service overrides.")
            ports = tuple(values)
        validated.append((name, environment, ports))
    return _ValidatedServiceOverrides(tuple(validated))


def apply_service_overrides(canonical_model, overrides):
    """Return a detached canonical Compose model with validated overrides applied.

    Environment keys merge into the targeted service's environment mapping; a
    supplied ports list replaces the full list. The input model and overrides are
    never modified.
    """
    if not isinstance(overrides, _ValidatedServiceOverrides):
        raise ValueError("Validated service overrides are required.")
    if not isinstance(canonical_model, dict) or not isinstance(
        canonical_model.get("services"), dict
    ):
        raise ValueError("Invalid canonical Compose model.")

    services = canonical_model["services"]
    for name, environment, _ports in overrides.services:
        if name not in services or not isinstance(services[name], dict):
            raise ValueError("Service overrides target an unknown service.")
        service = services[name]
        if environment is not None and service.get("environment") is not None and not isinstance(
            service["environment"], dict
        ):
            raise ValueError("Invalid canonical Compose model.")

    try:
        result = copy.deepcopy(canonical_model)
        for name, environment, ports in overrides.services:
            service = result["services"][name]
            if environment is not None:
                merged = service.get("environment")
                if merged is None:
                    merged = {}
                    service["environment"] = merged
                merged.update(environment)
            if ports is not None:
                service["ports"] = list(ports)
    except (TypeError, ValueError, copy.Error) as error:
        raise ValueError("Canonical Compose model cannot be copied.") from error
    return result


def _yaml_quoted(value):
    """Double-quoted YAML scalar using only escapes YAML 1.1 and 1.2 both accept."""
    parts = ['"']
    for char in value:
        code = ord(char)
        if char == '"':
            parts.append('\\"')
        elif char == "\\":
            parts.append("\\\\")
        elif 0x20 <= code < 0x7F:
            parts.append(char)
        elif code <= 0xFFFF:
            parts.append(f"\\u{code:04x}")
        else:
            parts.append(f"\\U{code:08x}")
    parts.append('"')
    return "".join(parts)


def _literal(value):
    """Escape Compose interpolation so the value reaches the container verbatim."""
    return _yaml_quoted(value.replace("$", "$$"))


def render_service_overrides(overrides):
    """Render validated overrides as a Compose override file applied after the sources.

    Environment keys merge into each service's environment; ``ports`` uses Compose's
    ``!override`` tag so the supplied list replaces the merged list. The canonical
    model is never round-tripped, so source-only syntax (for example ``build.ssh``)
    keeps the exact meaning Compose gives it.
    """
    if not isinstance(overrides, _ValidatedServiceOverrides):
        raise ValueError("Validated service overrides are required.")
    lines = ["services:"]
    for name, environment, ports in overrides.services:
        lines.append(f"  {_yaml_quoted(name)}:")
        if environment is not None:
            if environment:
                lines.append("    environment:")
                lines.extend(
                    f"      {_yaml_quoted(key)}: {_literal(value)}" for key, value in environment
                )
            else:
                lines.append("    environment: {}")
        if ports is not None:
            if ports:
                lines.append("    ports: !override")
                lines.extend(f"      - {_literal(port)}" for port in ports)
            else:
                lines.append("    ports: !override []")
        if environment is None and ports is None:
            lines[-1] += " {}"
    return "\n".join(lines) + "\n"
