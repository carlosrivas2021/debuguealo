import asyncio
from collections.abc import Callable, Coroutine
from contextlib import aclosing
from enum import StrEnum
from typing import Any, Self

from debugpilot.core.events import Event, EventBus
from debugpilot.core.exceptions import LifecycleError
from debugpilot.core.models import ContainerInfo, DiagnosticCheck
from debugpilot.core.protocols import DiagnosticsProvider, DockerProvider
from debugpilot.storage.config import Settings


class EngineState(StrEnum):
    NEW = "new"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"


class DebugPilotEngine:
    """Single-loop engine; interfaces own the loop, the engine owns its tasks.

    Task factories are evaluated only after lifecycle checks, avoiding unawaited
    coroutines on rejected operations. A closed engine cannot be restarted.
    """

    def __init__(
        self,
        settings: Settings,
        diagnostics: DiagnosticsProvider | None = None,
        docker: DockerProvider | None = None,
    ):
        self.settings = settings
        self.events = EventBus(settings.event_queue_size)
        self.state = EngineState.NEW
        self._diagnostics = diagnostics
        self._docker = docker
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closing: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self.state != EngineState.NEW:
            raise LifecycleError("An engine can only be started once.")
        self.state = EngineState.RUNNING

    def spawn(self, factory: Callable[[], Coroutine[Any, Any, Any]]) -> asyncio.Task[Any]:
        if self.state != EngineState.RUNNING:
            raise LifecycleError("The engine must be running before scheduling work.")
        task = asyncio.create_task(factory())
        self._tasks.add(task)
        task.add_done_callback(self._completed)
        return task

    def _completed(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            self.events.publish(Event(kind="task_failed", message="A background operation failed."))

    async def doctor(self) -> list[DiagnosticCheck]:
        if self._diagnostics is None:
            raise LifecycleError("No diagnostics provider has been configured.")
        return await self.spawn(self._diagnostics.inspect)

    async def list_containers(self) -> list[ContainerInfo]:
        if self._docker is None:
            raise LifecycleError("No Docker provider has been configured.")
        return await self.spawn(self._docker.list_containers)

    async def stream_logs(self, container: str, *, tail: int = 100, follow: bool = False):
        if self._docker is None:
            raise LifecycleError("No Docker provider has been configured.")
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        end = object()

        async def produce():
            try:
                try:
                    async with aclosing(
                        self._docker.stream_logs(container, tail=tail, follow=follow)
                    ) as source:
                        async for entry in source:
                            await queue.put(entry)
                except Exception as error:
                    await queue.put(error)
                await queue.put(end)
            finally:
                # Normal EOF preserves every record. Only cancellation may discard
                # one queued record to wake a consumer during engine shutdown.
                if asyncio.current_task().cancelling():
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(end)

        task = self.spawn(produce)
        try:
            while (entry := await queue.get()) is not end:
                if isinstance(entry, Exception):
                    raise entry
                yield entry
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _drain(self) -> None:
        try:
            tasks = tuple(self._tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self.state = EngineState.CLOSED

    async def close(self) -> None:
        if asyncio.current_task() in self._tasks:
            raise LifecycleError("Engine-owned tasks cannot close their own engine.")
        if self._closing is None:
            self.state = EngineState.CLOSING
            self._closing = asyncio.create_task(self._drain())
        try:
            await asyncio.shield(self._closing)
        except asyncio.CancelledError:
            await self._closing
            raise

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
