"""Native detail rendering for the currently selected Docker container."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.widgets import DataTable, Static

from debugpilot.core.models import ContainerInfo, PortMapping
from debugpilot.tui.container_list import group_style, state_glyph


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
        glyph, color = state_glyph(container.state)
        title = Text.assemble(
            (f"{glyph} ", color),
            (container.name, "bold"),
            (f"  {container.state}", color),
            ("  ·  Ctrl+L logs", "bright_black"),
            no_wrap=True,
            overflow="ellipsis",
        )
        self.query_one("#container-details-title", Static).update(title)
        labels = container.labels
        ports = published_ports(container)
        values = (
            (
                ("State", container.state),
                ("Uptime", container.status or "—"),
                ("Created", f"{container.created_at:%Y-%m-%d}"),
            ),
            (
                ("Name", container.name),
                ("Image", container.image),
                ("ID", container.id[:12]),
            ),
            (("Published ports", ""), *((None, port) for port in ports.split(", "))),
            (
                ("Project", container.compose_project or "—"),
                ("Service", container.compose_service or "—"),
                ("Folder", labels.get("com.docker.compose.project.working_dir") or "—"),
            ),
        )
        for card, lines in zip(self.cards(), values, strict=True):
            card.update(_card_text(lines, state_color=color))
            card.set_class(card.border_title == "Status", f"state-{_state_class(container)}")


def _card_text(lines, *, state_color: str) -> Text:
    """Render `Key: value` lines with muted keys so the values carry the weight."""
    text = Text()
    for index, (key, value) in enumerate(lines):
        if index:
            text.append("\n")
        if key is not None:
            text.append(f"{key}:", style="#7f8c93")
            if value:
                text.append(" ")
        empty = value in {"—", "None published"}
        style = state_color if key == "State" else ("bright_black" if empty else "#e3e7ea")
        text.append(value, style=style)
    return text


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
                ports if (ports := published_ports(member)) != "None published" else "—",
                member.image,
            )
            for member in members
        )
        running = sum(member.state == "running" for member in members)
        if (project, running, rows) == self._content:
            return  # Refreshes repeat the inventory; keep the table untouched.
        self._content = (project, running, rows)
        self.query_one("#project-overview-title", Static).update(
            Text.assemble(
                (project, "bold"),
                " · ",
                (f"{running} / {len(rows)} running", group_style(running, len(rows))),
                (" · Ctrl+L logs", "bright_black"),
                no_wrap=True,
                overflow="ellipsis",
            )
        )
        table = self.query_one(DataTable)
        table.clear()
        for service, state, uptime, ports, image in rows:
            glyph, color = state_glyph(state)
            table.add_row(
                service,
                Text(f"{glyph} {state}", style=color),
                uptime,
                ports,
                image,
            )
