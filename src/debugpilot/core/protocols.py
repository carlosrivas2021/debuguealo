from typing import Protocol

from debugpilot.core.models import DiagnosticCheck


class DiagnosticsProvider(Protocol):
    async def inspect(self) -> list[DiagnosticCheck]:
        """Return bounded, safe diagnostics without exposing SDK exceptions."""
        ...
