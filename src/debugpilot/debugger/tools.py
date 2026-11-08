"""Availability checks for the external tools that Code debugging relies on."""

import shutil

from debugpilot.core.models import CheckStatus, DiagnosticCheck

DELVE_INSTALL = "go install github.com/go-delve/delve/cmd/dlv@latest"


def debug_tool_checks() -> list[DiagnosticCheck]:
    """Report Delve; a missing tool is a warning, never an error.

    Go debugging resolves ``dlv`` on PATH. Python debugging needs no check: debugealo
    bundles debugpy and runs the adapter on its own interpreter.
    """
    return [_delve_check()]


def _delve_check() -> DiagnosticCheck:
    dlv = shutil.which("dlv")
    if dlv:
        return DiagnosticCheck(name="Delve", status=CheckStatus.OK, detail=f"Go debugging: {dlv}")
    return DiagnosticCheck(
        name="Delve",
        status=CheckStatus.WARNING,
        detail=f"Not on PATH; needed for Go debugging. Install: {DELVE_INSTALL}",
    )
