# Reuse the engine without a terminal

`core` owns its lifecycle and background tasks; no core, storage, or Docker module imports
Textual. The CLI is a composition root: it injects `DockerDiagnostics` through a small
protocol. Domain diagnostics and bounded events are Pydantic models, not widgets.

```python
import asyncio

from debugealo.core.engine import DebugPilotEngine
from debugealo.docker.diagnostics import DockerDiagnostics
from debugealo.storage.config import load_settings


async def main():
    settings = load_settings()
    async with DebugPilotEngine(settings, DockerDiagnostics(settings)) as engine:
        for check in await engine.doctor():
            print(check.name, check.status, check.detail)


asyncio.run(main())
```

## Lifecycle and bounds

The lifecycle is `new → running → closing → closed`. Engines are single-loop and not
restartable. `spawn` takes a coroutine factory so rejecting a task does not leak a coroutine.
Closing cancels owned tasks, awaits their cleanup, and observes failures without printing
exception values. Tasks must cooperate with cancellation. Consumers own subscriptions and
pending event reads; use an engine-owned task for long-running consumers.

Each event has bounded strings and each subscriber has a bounded drop-oldest queue.
The current bus is only for control notifications; logs need a separate bounded buffer.
It does not guarantee lossless delivery. No history, variable values, telemetry, or SQLite
database are written. SQLite will be introduced only for an identified persistence need.

Docker's synchronous SDK executes in a short-lived worker process with a private empty
Docker config and a minimal environment. This prevents reading ambient Docker credentials
or selecting a remote context. Requests environment/proxy discovery is disabled. Normal
completion closes the SDK client. Cancellation or the end-to-end deadline kills and reaps
the worker, then removes its temporary config. Diagnostic output is capped at 4 KiB.
The Docker service uses the same isolated-process pattern for container and log reads,
without changing the diagnostic protocol. JSON-lines records preserve backpressure; its
Engine API log reader bounds frames and preserves stdout/stderr stream IDs.

## Future presentation adapters

Textual can own its asyncio loop and enter/close the same engine in mount/unmount hooks.
For a future PySide6 frontend, select and validate a Qt-compatible asyncio adapter (for
example qasync), instantiate the engine on that loop, and render domain events into widgets.
Do not call `asyncio.run` inside a running Qt loop. No Qt dependency is introduced now.

## Delivery status

The MVP is implemented: the engine, Docker discovery and logs, the TUI, Python, Node and Go
debugging over DAP or Inspector, attach to existing targets, and the
[FastAPI debug example](../examples/fastapi-debug/README.md). The PySide6 frontend is not started.
See `odd/tasks/debugpilot-mvp.md` for the original specification.
