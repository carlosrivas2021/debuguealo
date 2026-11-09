"""Stable, namespaced presentation rows for Compose projects and their containers."""

from dataclasses import dataclass

from debugpilot.core.models import ContainerInfo


@dataclass(frozen=True)
class ContainerRow:
    key: str
    label: str
    state: str
    service: str = ""
    container: ContainerInfo | None = None
    project: str | None = None


_STATE_GLYPHS = {
    "running": ("●", "green"),
    "restarting": ("↻", "yellow"),
    "paused": ("◐", "yellow"),
    "exited": ("○", "red"),
    "dead": ("✕", "red"),
}


def state_glyph(state: str) -> tuple[str, str]:
    """Return a shape-distinct glyph and color so state reads without relying on color."""
    return _STATE_GLYPHS.get(state, ("○", "bright_black"))


def group_style(running: int, total: int) -> str:
    """Color for an `active/total` group counter: all up, partially up, or all down."""
    if total and running == total:
        return "bold green"
    return "bold yellow" if running else "bold bright_black"


def container_label(item: ContainerInfo) -> str:
    if item.compose_project:
        for separator in ("-", "_"):
            prefix = item.compose_project + separator
            if item.name.startswith(prefix) and len(item.name) > len(prefix):
                return item.name[len(prefix) :]
    return item.name


def container_rows(inventory: list[ContainerInfo]) -> list[ContainerRow]:
    groups: dict[str | None, list[ContainerInfo]] = {}
    for item in inventory:
        groups.setdefault(item.compose_project or None, []).append(item)
    projects = sorted((name for name in groups if name is not None), key=str.casefold)
    rows = []
    for project in [*projects, *([None] if None in groups else [])]:
        members = sorted(
            groups[project],
            key=lambda item: (
                (item.compose_service or item.name).casefold(),
                item.name.casefold(),
                item.id,
            ),
        )
        running = sum(item.state == "running" for item in members)
        rows.append(
            ContainerRow(
                key=f"project:{project}" if project is not None else "standalone:",
                label=f"▾ {project}" if project is not None else "▾ Standalone",
                state=f"{running}/{len(members)}",
                project=project,
            )
        )
        rows.extend(
            ContainerRow(
                key=f"container:{item.id}",
                label=f"  {container_label(item)}",
                state=item.state,
                service=item.compose_service or "—",
                container=item,
                project=project,
            )
            for item in members
        )
    return rows
