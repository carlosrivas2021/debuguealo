from collections.abc import AsyncIterator
from typing import Protocol

from debugpilot.core.models import ContainerInfo, DiagnosticCheck, LogEntry


class DiagnosticsProvider(Protocol):
    async def inspect(self) -> list[DiagnosticCheck]:
        """Return bounded, safe diagnostics without exposing SDK exceptions."""
        ...


class DockerProvider(Protocol):
    async def list_containers(self) -> list[ContainerInfo]: ...

    def stream_logs(
        self, container: str, *, tail: int = 100, follow: bool = False
    ) -> AsyncIterator[LogEntry]: ...
