import asyncio
import json
import platform
import sys
from contextlib import aclosing
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from debugpilot import __version__
from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import ConfigurationError, DockerError
from debugpilot.core.models import CheckStatus, DiagnosticCheck
from debugpilot.debugger.tools import debug_tool_checks
from debugpilot.docker.diagnostics import DockerDiagnostics, endpoint_description
from debugpilot.docker.service import DockerService
from debugpilot.storage.config import load_settings

app = typer.Typer(
    name="debugealo",
    no_args_is_help=False,
    invoke_without_command=True,
    help="debugealo: local Docker debugging. Inspect containers, logs, and environment health.",
    pretty_exceptions_enable=False,
)
console = Console(markup=False)


@app.callback()
def main(ctx: typer.Context) -> None:
    """Open the terminal dashboard when no command is supplied."""
    if ctx.invoked_subcommand is None:
        _launch_tui()


def _launch_tui(config: Path | None = None) -> None:
    # Keep non-interactive CLI commands and the core independent of Textual.
    from debugpilot.tui.app import DebugPilotApp

    try:
        DebugPilotApp(_docker_engine(config)).run()
    except ConfigurationError as error:
        console.print(f"Configuration error: {error}", style="red")
        raise typer.Exit(2) from None
    except KeyboardInterrupt:
        raise typer.Exit(130) from None


@app.command()
def tui(
    config: Annotated[Path | None, typer.Option(help="Optional TOML configuration path.")] = None,
) -> None:
    """Open the keyboard-first container and live log dashboard."""
    _launch_tui(config)


@app.command()
def version() -> None:
    """Print the installed debugealo version."""
    console.print(f"debugealo {__version__}")


@app.command()
def doctor(
    config: Annotated[Path | None, typer.Option(help="Optional TOML configuration path.")] = None,
) -> None:
    """Check Python, configuration, Docker access, and the Delve and debugpy debug tools."""
    try:
        settings = load_settings(config)
    except ConfigurationError as error:
        console.print(f"Configuration error: {error}", style="red")
        raise typer.Exit(2) from None

    async def diagnose() -> list[DiagnosticCheck]:
        async with DebugPilotEngine(settings, DockerDiagnostics(settings)) as engine:
            return await engine.doctor()

    checks = [
        DiagnosticCheck(
            name="Python",
            status=CheckStatus.OK if sys.version_info >= (3, 12) else CheckStatus.ERROR,
            detail=platform.python_version(),
        ),
        DiagnosticCheck(name="Environment", status=CheckStatus.OK, detail=platform.system()),
        DiagnosticCheck(
            name="Configuration", status=CheckStatus.OK, detail="Validated; no files written"
        ),
        DiagnosticCheck(
            name="Endpoint", status=CheckStatus.OK, detail=endpoint_description(settings)
        ),
        *asyncio.run(diagnose()),
        *debug_tool_checks(),
    ]
    table = Table("Check", "Status", "Details")
    for check in checks:
        table.add_row(check.name, check.status.value, check.detail)
    console.print(table)
    if any(check.status == CheckStatus.ERROR for check in checks):
        raise typer.Exit(1)


def _docker_engine(config: Path | None) -> DebugPilotEngine:
    settings = load_settings(config)
    return DebugPilotEngine(settings, docker=DockerService(settings))


def _run_docker(operation):
    try:
        return asyncio.run(operation())
    except (DockerError, ConfigurationError) as error:
        console.print(f"Error: {error}", style="red")
        raise typer.Exit(1) from None
    except ValueError:
        console.print("Invalid Docker input or configuration.", style="red")
        raise typer.Exit(2) from None
    except KeyboardInterrupt:
        raise typer.Exit(130) from None


@app.command()
def containers(
    config: Annotated[Path | None, typer.Option(help="Optional TOML configuration path.")] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Include all metadata as JSON.")
    ] = False,
) -> None:
    """List running and stopped local containers, including Compose metadata."""

    async def discover():
        async with _docker_engine(config) as engine:
            return await engine.list_containers()

    inventory = _run_docker(discover)
    if json_output:
        typer.echo(json.dumps([item.model_dump(mode="json") for item in inventory]))
        return
    table = Table("ID", "Name", "Image", "State", "Compose", "Created", "Ports")
    for item in inventory:
        ports = ", ".join(
            f"{port.host_ip or '*'}:{port.public_port or '-'}->{port.private_port}/{port.protocol}"
            for port in item.ports
        )
        compose = "/".join(filter(None, (item.compose_project, item.compose_service)))
        table.add_row(
            item.id[:12],
            item.name,
            item.image,
            item.state,
            compose,
            item.created_at.isoformat(),
            ports,
        )
    console.print(table)
    if not inventory:
        console.print("No containers found.")


@app.command()
def logs(
    container: Annotated[str, typer.Argument(help="Container name or ID.")],
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help="Follow new logs; Ctrl+C to stop.")
    ] = False,
    tail: Annotated[
        int, typer.Option(min=0, max=10_000, help="Historical lines to request.")
    ] = 100,
    config: Annotated[Path | None, typer.Option(help="Optional TOML configuration path.")] = None,
) -> None:
    """Read bounded history or follow live logs without changing a container."""

    async def consume():
        async with _docker_engine(config) as engine:
            async with aclosing(engine.stream_logs(container, tail=tail, follow=follow)) as entries:
                async for entry in entries:
                    suffix = " [truncated]" if entry.truncated else ""
                    console.print(
                        Text(f"{entry.timestamp or '-'} [{entry.stream}] {entry.text}{suffix}")
                    )

    _run_docker(consume)


credentials_app = typer.Typer(help="Refresh credentials used by launch profiles.")
app.add_typer(credentials_app, name="credentials")


@credentials_app.command("refresh")
def refresh_credentials() -> None:
    """Write fresh AWS credentials into every launch profile's awsCredentials files."""
    from debugpilot.storage.aws_credentials import refresh_targets
    from debugpilot.storage.launch_profiles import LaunchProfileStore

    try:
        targets = LaunchProfileStore().aws_credential_targets()
    except ConfigurationError as error:
        console.print(f"Configuration error: {error}", style="red")
        raise typer.Exit(2) from None
    if not targets:
        console.print("No launch profiles declare awsCredentials.")
        raise typer.Exit(1)
    result = refresh_targets(
        (profile.name or profile.project_name or "profile", target) for profile, target in targets
    )
    for path in result.updated_files:
        console.print(f"Updated {path}")
    for label, expiration in result.expirations.items():
        console.print(f"AWS profile {label} credentials expire at {expiration}.")
    for error in result.errors:
        console.print(error, style="red")
    if result.profiles:
        console.print(
            "Recreate these profiles to apply the new credentials: " + ", ".join(result.profiles)
        )
    if result.errors:
        raise typer.Exit(1)
