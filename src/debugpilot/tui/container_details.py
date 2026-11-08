"""Native detail rendering for the currently selected Docker container."""

from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.widgets import DataTable, Static

from debugpilot.core.models import ContainerInfo, PortMapping


def format_published_port(port: PortMapping) -> str | None:
    """Format only Docker bindings with an assigned public port."""
    if port.public_port is None:
        return None
    host = port.host_ip
    if host:
        if ":" in host and not (host.startswith("[") and host.endswith("]")):
            host = f"[{host}]"
        binding = f"{host}:{port.public_port}"
    else:
        binding = str(port.public_port)
    return f"{binding}->{port.private_port}/{port.protocol}"


def published_ports(container: ContainerInfo) -> str:
    bindings = [value for port in container.ports if (value := format_published_port(port))]
    return ", ".join(bindings) if bindings else "None published"


class ContainerDetails(Vertical):
    """Four cards populated exclusively from the selected inventory record."""

    CARDS = ("Status", "Image", "Network", "Compose")

    def compose(self) -> ComposeResult:
        yield Static("Container details · Ctrl+L logs", id="container-details-title", markup=False)
        with Grid(id="detail-cards"):
            for title in self.CARDS:
                card = Static("", classes="detail-card", markup=False)
                card.border_title = title
                yield card

    def cards(self) -> list[Static]:
        return list(self.query(".detail-card").results(Static))

    def text(self) -> str:
        """Plain text of every card, in display order."""
        return "\n".join(str(card.render()) for card in self.cards())

    def show_container(self, container: ContainerInfo) -> None:
        self.query_one("#container-details-title", Static).update(
            f"Container details · {container.name} · Ctrl+L logs"
        )
        labels = container.labels
        values = (
            (
                f"State: {container.state}",
                f"Uptime: {container.status or '—'}",
                f"Created: {container.created_at:%Y-%m-%d}",
            ),
            (
                f"Name: {container.name}",
                f"Image: {container.image}",
                f"ID: {container.id[:12]}",
            ),
            ("Published ports:", *published_ports(container).split(", ")),
            (
                f"Project: {container.compose_project or '—'}",
                f"Service: {container.compose_service or '—'}",
                f"Folder: {labels.get('com.docker.compose.project.working_dir') or '—'}",
            ),
        )
        for card, lines in zip(self.cards(), values, strict=True):
            card.update("\n".join(lines))
            card.set_class(card.border_title == "Status", f"state-{_state_class(container)}")


def _state_class(container: ContainerInfo) -> str:
    return container.state if container.state in {"running", "exited", "paused"} else "other"


class ProjectOverview(Vertical):
    """Compose project members at a glance; logs stay closed until requested."""

    COLUMNS = ("Service", "State", "Uptime", "Ports", "Image")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._content: tuple | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="project-overview-title", markup=False)
        yield DataTable(id="project-overview-table", cursor_type="none", zebra_stripes=True)

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(*self.COLUMNS)

    def show_project(self, project: str, members) -> None:
        rows = tuple(
            (
                member.compose_service or member.name,
                member.state,
                member.status or "—",
                published_ports(member),
                member.image,
            )
            for member in members
        )
        running = sum(member.state == "running" for member in members)
        title = f"{project} · {running} / {len(rows)} running · Ctrl+L logs"
        if (title, rows) == self._content:
            return  # Refreshes repeat the inventory; keep the table untouched.
        self._content = (title, rows)
        self.query_one("#project-overview-title", Static).update(title)
        table = self.query_one(DataTable)
        table.clear()
        for row in rows:
            table.add_row(*row)
