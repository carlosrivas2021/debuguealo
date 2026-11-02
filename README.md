# DebugPilot

Local-first Docker debugging in Python. **Implementation is in progress; this is not the completed MVP.**

## Current executable slice

The foundation provides packaging, a headless lifecycle engine, bounded events, TOML
configuration, and real local Docker diagnostics. Docker integration adds discovery of
running/stopped containers, Compose metadata, historical/live logs, bounded buffering,
and controlled reconnect/cancellation. The terminal dashboard adds keyboard selection,
live logs, bounded search/filter/pause controls and explicit connection errors.
The **Code** area now registers explicitly configured project folders using a separate
central `projects/launch.json`; see [code project registration](docs/code-projects.md).
Code execution, DAP and the FastAPI example remain pending.
No connection is simulated in the application.

The dashboard also supports explicit, confirmation-gated local Compose restart,
recreate and rebuild actions for a service or project, using ordered override files.
Press Ctrl+O to open launch.json; read [Compose safety and limits](docs/compose.md) before running actions.

The primary sidebar lists saved configurations from a central `launch.json` beside
DebugPilot's user `config.toml`, independent of the working directory. Each central
profile explicitly names its project root with `workspaceFolder`; the previous
`.debugpilot/launch.json` local-workspace mode remains supported for explicit callers
and is not auto-migrated. Running containers are linked by the explicit Compose `projectName`,
not by the display label. Profiles remain available when no containers are running.
The lower **View active containers** area shows Docker inventory separately, including
containers not configured in the launch file; selecting raw inventory does not authorize
Compose actions.

With no saved profiles, a welcome view offers **Open launch.json**. **Ctrl+O** and
**Ctrl+N** request the same editor action directly, without a Compose picker. If absent,
the central file is created only on that explicit action as an empty configuration array.
Existing
files are never replaced. The TUI yields the same terminal to `nano` (or `vi` if
`nano` is unavailable), waits for you to exit, then restores the dashboard and reloads
the profiles. No VS Code window or system file association is opened. Install `nano`
or `vi` on PATH if neither is available. In nano, save with Ctrl+O, Enter, then exit
with Ctrl+X; in vi, use `:wq` to save and exit. No second discovery JSON is created.

Select a saved profile, then use **Play / Recreate** (`r`) to apply Compose configuration,
environment and port changes, or **Build + Recreate** (`Shift+R`) when code or image
dependencies changed. Plain Restart is not exposed in the dashboard. Each action shows
an inline confirmation with the pinned profile; changing its saved configuration before
confirmation invalidates the preview. Escape cancels without running Docker. Builds
and recreation may interrupt services; inspect Docker after partial failures.

The selected profile follows its project's combined logs, tagged by container origin.
Raw inventory also supports individual service logs. **Ctrl+R** reconnects the current
selection. Dashboard logs show only each container's current execution. Successful
recreation refreshes inventory, clears the old view and reconnects after container IDs
change; Docker's stored history is not deleted. The `logs` CLI retains history behavior.
See the [keyboard workflow](docs/tui.md) and [workspace launch profiles](docs/launch-profiles.md).
Press **s** or click **Stop** to confirm stopping a container or its selected project
group, without removing containers or volumes. See [container controls](docs/container-controls.md).
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
