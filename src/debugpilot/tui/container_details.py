"""Native detail rendering for the currently selected Docker container."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.widgets import DataTable, Static

from debugpilot.core.models import ContainerInfo, ContainerRuntime, ContainerStats, PortMapping
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


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def format_memory(stats: ContainerStats | None) -> str:
    if stats is None or stats.memory_usage is None:
        return "—"
    text = format_bytes(stats.memory_usage)
    if stats.memory_limit:
        share = stats.memory_usage / stats.memory_limit * 100
        text += f" / {format_bytes(stats.memory_limit)} ({share:.1f}%)"
    return text


def published_ports(container: ContainerInfo) -> str:
    bindings = [value for port in container.ports if (value := format_published_port(port))]
    return ", ".join(bindings) if bindings else "None published"


class ContainerDetails(Vertical):
    """Inventory cards for the selected record, plus a Runtime card from its inspect."""

    CARDS = ("Status", "Image", "Network", "Compose", "Runtime")
    MAX_ENV_TEXT = 160

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._container: ContainerInfo | None = None
        self._cpu = "—"
        self._memory = "—"
        self._runtime: ContainerRuntime | None = None

    def compose(self) -> ComposeResult:
        yield Static("Container details · Ctrl+L logs", id="container-details-title", markup=False)
        with Grid(id="detail-cards"):
            for title in self.CARDS:
                classes = "detail-card wide" if title == "Runtime" else "detail-card"
                card = Static("", classes=classes, markup=False)
                card.border_title = title
                yield card

    def cards(self) -> list[Static]:
        return list(self.query(".detail-card").results(Static))

    def text(self) -> str:
        """Plain text of every card, in display order."""
        return "\n".join(str(card.render()) for card in self.cards())

    def show_stats(self, cpu: float | None, stats: ContainerStats | None) -> None:
        """Live CPU and memory for the shown container; None shows a dash."""
        self._cpu = "—" if cpu is None else f"{cpu:.1f}%"
        self._memory = format_memory(stats)
        if self._container is not None:
            self.show_container(self._container)

    def show_runtime(self, runtime: ContainerRuntime | None) -> None:
        """Inspect facts for the shown container; None shows dashes."""
        self._runtime = runtime
        if self._container is not None:
            self.show_container(self._container)

    def show_container(self, container: ContainerInfo) -> None:
        if self._container is None or self._container.id != container.id:
            # Another container: its predecessor's numbers must not linger.
            self._cpu = self._memory = "—"
            self._runtime = None
        self._container = container
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
                ("CPU", self._cpu),
                ("Memory", self._memory),
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
            self._runtime_lines(container),
        )
        for card, lines in zip(self.cards(), values, strict=True):
            card.update(_card_text(lines, state_color=color))
            card.set_class(card.border_title == "Status", f"state-{_state_class(container)}")


    def _runtime_lines(self, container: ContainerInfo) -> tuple:
        runtime = self._runtime
        if runtime is None:
            return (("Health", "—"), ("Restart", "—"), ("Mounts", "—"), ("Env", "—"))
        health = runtime.health or "—"
        if runtime.health and runtime.health_output:
            health += f" · {runtime.health_output}"
        restart = runtime.restart_policy or "—"
        if runtime.restart_count:
            noun = "restart" if runtime.restart_count == 1 else "restarts"
            restart += f" · {runtime.restart_count} {noun}"
        lines = [("Health", health), ("Restart", restart)]
        if container.state != "running" and runtime.exit_code is not None:
            code = str(runtime.exit_code)
            lines.append(("Exit code", f"{code} (OOM killed)" if runtime.oom_killed else code))
        if runtime.mounts:
            lines.append(("Mounts", ""))
            for mount in runtime.mounts:
                source = f"{mount.source} → " if mount.source else ""
                access = " (read-only)" if mount.read_only else ""
                lines.append((None, f"{mount.type} {source}{mount.destination}{access}"))
        else:
            lines.append(("Mounts", "None"))
        if runtime.env_names:
            count = len(runtime.env_names)
            names = ", ".join(runtime.env_names)
            if len(names) > self.MAX_ENV_TEXT:
                names = names[:self.MAX_ENV_TEXT - 1] + "…"
            noun = "variable" if count == 1 else "variables"
            lines.append(("Env", f"{count} {noun}, values hidden · {names}"))
        else:
            lines.append(("Env", "None"))
        return tuple(lines)


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
        empty = value in {"—", "None published", "None"}
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
