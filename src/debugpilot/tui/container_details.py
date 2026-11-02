"""Native detail rendering for the currently selected Docker container."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

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
    """Compact pane populated exclusively from the selected inventory record."""

    DEFAULT_CSS = "ContainerDetails { height: auto; max-height: 10; padding: 0 1; }"

    def compose(self) -> ComposeResult:
        yield Static("Container details · D", id="container-details-title", markup=False)
        yield Static("Select a container", id="container-details-content", markup=False)

    def show_container(self, container: ContainerInfo) -> None:
        self.query_one("#container-details-title", Static).update(
            f"Container details · {container.name}"
        )
        self.query_one("#container-details-content", Static).update(
            "\n".join(
                (
                    f"Name: {container.name}",
                    f"Image: {container.image}",
                    f"State: {container.state}",
                    f"Project: {container.compose_project or '—'}",
                    f"Service: {container.compose_service or '—'}",
                    f"Published ports: {published_ports(container)}",
                )
            )
        )
