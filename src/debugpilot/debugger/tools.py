"""Availability checks for the external tools that Code debugging relies on."""

import shutil
import subprocess

from debugpilot.core.models import CheckStatus, DiagnosticCheck

DELVE_INSTALL = "go install github.com/go-delve/delve/cmd/dlv@latest"
# find_spec locates debugpy without importing or running it.
_HAS_DEBUGPY = "import importlib.util, sys; sys.exit(importlib.util.find_spec('debugpy') is None)"


def debug_tool_checks() -> list[DiagnosticCheck]:
    """Report Delve and debugpy; missing tools are warnings, never errors.

    Go debugging resolves ``dlv`` on PATH. Python debugging runs debugpy in each
    profile's own interpreter, so only the default ``python3`` can be checked here.
    """
    return [_delve_check(), _debugpy_check()]


def _delve_check() -> DiagnosticCheck:
    dlv = shutil.which("dlv")
    if dlv:
        return DiagnosticCheck(name="Delve", status=CheckStatus.OK, detail=f"Go debugging: {dlv}")
    return DiagnosticCheck(
        name="Delve",
        status=CheckStatus.WARNING,
        detail=f"Not on PATH; needed for Go debugging. Install: {DELVE_INSTALL}",
    )


def _debugpy_check() -> DiagnosticCheck:
    python = shutil.which("python3") or shutil.which("python")
    if python is None:
        return DiagnosticCheck(
            name="debugpy",
            status=CheckStatus.WARNING,
            detail="No python3 on PATH; each Python profile's interpreter needs debugpy.",
        )
    try:
        found = (
            subprocess.run(
                [python, "-c", _HAS_DEBUGPY], capture_output=True, timeout=5, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return DiagnosticCheck(
            name="debugpy", status=CheckStatus.UNKNOWN, detail=f"Could not check {python}"
        )
    if found:
        return DiagnosticCheck(
            name="debugpy",
            status=CheckStatus.OK,
            detail=f"Found in {python}; each Python profile uses its own interpreter",
        )
    return DiagnosticCheck(
        name="debugpy",
        status=CheckStatus.WARNING,
        detail=(
            f"Not installed in {python}. Install it in each Python profile's interpreter, "
            f"e.g. {python} -m pip install debugpy"
        ),
    )
