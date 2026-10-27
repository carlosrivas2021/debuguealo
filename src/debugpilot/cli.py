import asyncio
import platform
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from debugpilot import __version__
from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import ConfigurationError
from debugpilot.core.models import CheckStatus, DiagnosticCheck
from debugpilot.docker.diagnostics import DockerDiagnostics, endpoint_description
from debugpilot.storage.config import load_settings

app = typer.Typer(
    no_args_is_help=True,
    help="Local Docker debugging toolkit. Foundation preview: doctor and version are available.",
    pretty_exceptions_enable=False,
)
console = Console(markup=False)


@app.command()
def version() -> None:
    """Print the installed DebugPilot version."""
    console.print(f"DebugPilot {__version__}")


@app.command()
def doctor(
    config: Annotated[Path | None, typer.Option(help="Optional TOML configuration path.")] = None,
) -> None:
    """Check Python, configuration, and read access to the local Docker daemon."""
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
    ]
    table = Table("Check", "Status", "Details")
    for check in checks:
        table.add_row(check.name, check.status.value, check.detail)
    console.print(table)
    if any(check.status == CheckStatus.ERROR for check in checks):
        raise typer.Exit(1)
