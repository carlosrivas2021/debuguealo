# DebugPilot

Local-first Docker debugging in Python. **Implementation is in progress; this is not the completed MVP.**

## Current executable slice

The foundation provides packaging, a headless lifecycle engine, bounded events, TOML
configuration, and real local Docker diagnostics. Docker integration adds discovery of
running/stopped containers, Compose metadata, historical/live logs, bounded buffering,
and controlled reconnect/cancellation. The terminal dashboard adds keyboard selection,
live logs, bounded search/filter/pause controls and explicit connection errors.
DAP and the FastAPI example remain pending.
No connection is simulated in the application.

The dashboard also supports explicit, confirmation-gated local Compose restart,
recreate and rebuild actions for a service or project, using ordered override files.
Press Ctrl+O; read [Compose safety and limits](docs/compose.md) before using them.

Containers are grouped by Compose project. Select a service or project header, then
press `r` to request restart or `Shift+R` to request rebuild/recreate; both require
preview and confirmation. `Ctrl+R` retries logs. Try the
[three-project network laboratory](docs/multi-project.md) with isolated demo services.

Use **Open Compose** / **Ctrl+N** to browse and start a project from its Compose file.
The default inventory shows active containers; **Show all** reveals stopped containers
in a separate section. See [file-based startup](docs/starting-projects.md).

```console
uv sync --locked
uv run debugpilot
uv run debugpilot tui
uv run debugpilot version
uv run debugpilot doctor
uv run debugpilot containers
uv run debugpilot containers --json
uv run debugpilot logs payments-api --tail 100
uv run debugpilot logs payments-api --follow
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

```powershell
$uv = 'C:\Users\Usuario\Documents\Development\motorsonido\.tools\bin\uv.exe'
& $uv sync --locked
& $uv run debugpilot doctor
```


Install Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
On Windows, use PowerShell and Docker Desktop in Linux-container mode. On macOS,
use Docker Desktop; on Linux, use Docker Engine and grant your account socket access
according to your organization's policy. Docker access is privileged; do not expose its
socket, make it world-writable, or run DebugPilot as administrator to mask configuration errors.

`doctor` exits 0 when all checks pass, 1 for an unavailable/denied Docker daemon,
and 2 for invalid configuration. It reports Python, configuration, platform, local endpoint,
connectivity, permissions, and Docker server version. A successful API read proves access
to that operation, not authorization for every Docker API operation.

Configuration is optional. See [configuration](docs/configuration.md) and
[architecture](docs/architecture.md). Usage after installation requires no Internet.
Dependency installation and the eventual example image build may require downloads.

## Not available yet

`debugpilot` and `debugpilot tui` open the terminal dashboard; see the
[keyboard workflow](docs/tui.md). The future `gui` command is not registered.
The FastAPI example and first-breakpoint walkthrough will arrive with the real DAP integration.
No license has been selected; no license grant is implied by this source distribution.

Read [Docker integration](docs/docker.md) for limits, logging-driver support, and reconnect semantics.
