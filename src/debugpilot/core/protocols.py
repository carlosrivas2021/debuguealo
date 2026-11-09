from collections.abc import AsyncIterator
from typing import Protocol

from debugpilot.core.models import (
    ContainerInfo,
    ContainerStats,
    DiagnosticCheck,
    LogEntry,
    StopResult,
)


class DiagnosticsProvider(Protocol):
    async def inspect(self) -> list[DiagnosticCheck]:
        """Return bounded, safe diagnostics without exposing SDK exceptions."""
        ...


class DockerProvider(Protocol):
    async def list_containers(self) -> list[ContainerInfo]: ...

    async def container_stats(self, container: str) -> ContainerStats: ...

    async def stop_containers(
        self,
        containers: tuple[str, ...],
        *,
        confirmed: bool = False,
        timeout_seconds: int = 10,
    ) -> StopResult: ...

    def stream_logs(
        self, container: str, *, tail: int = 100, follow: bool = False, current_run: bool = False
    ) -> AsyncIterator[LogEntry]: ...
