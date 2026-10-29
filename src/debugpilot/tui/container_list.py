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
                label=f"▾ {project}" if project is not None else "▾ Standalone containers",
                state=f"{running}/{len(members)} running",
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
