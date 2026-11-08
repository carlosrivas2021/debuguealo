# debugealo

Local-first Docker debugging in Python.

## What it does

The foundation provides packaging, a headless lifecycle engine, bounded events, TOML
configuration, and real local Docker diagnostics. Docker integration adds discovery of
running/stopped containers, Compose metadata, historical/live logs, bounded buffering,
and controlled reconnect/cancellation. The terminal dashboard adds keyboard selection,
live logs, bounded search/filter/pause controls and explicit connection errors.
The **Code** area registers project folders using a separate central `projects/launch.json`
and runs the selected profile without debug using **F5**, with an interactive console and
**Stop** control. **Shift+F5** debugs Python and supported Go profiles with the same
profile: mark read-only source, pause at a breakpoint, inspect stack/variables, step and
Continue. Go attach profiles can connect to an existing loopback Delve target without
starting or owning that target; disconnect leaves its lifecycle to Containers. Requested
breakpoints remain separate from adapter verification. Python debug
requires `debugpy` in the selected interpreter; Go debug requires Delve (`dlv`) on the
application PATH. Debug mode has no interactive stdin, and missing adapters never fall
back to run. See [code projects](docs/code-projects.md), including the Go remote attach schema,
source mapping, controls and reconnect workflow. Python attach profiles do the same for an
existing loopback `debugpy` target, such as a container; try the
[FastAPI debug example](examples/fastapi-debug/README.md). Server-side Node debugging
supports direct scripts and explicit npm debug targets; see [code projects](docs/code-projects.md#debug-server-side-node).
No connection is simulated in the application.

The dashboard also supports explicit, confirmation-gated local Compose restart,
recreate and rebuild actions for a service or project, using ordered override files.
Press Ctrl+O to open launch.json; read [Compose safety and limits](docs/compose.md) before running actions.

The primary sidebar lists saved configurations from a central `launch.json` beside
debugealo's user `config.toml`, independent of the working directory. Each central
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
uv run debugealo
uv run debugealo tui
uv run debugealo version
uv run debugealo doctor
uv run debugealo containers
uv run debugealo containers --json
uv run debugealo logs payments-api --tail 100
uv run debugealo logs payments-api --follow
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

```powershell
$uv = 'C:\Users\Usuario\Documents\Development\motorsonido\.tools\bin\uv.exe'
& $uv sync --locked
& $uv run debugealo doctor
```


Install Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
On Windows, use PowerShell and Docker Desktop in Linux-container mode. On macOS,
use Docker Desktop; on Linux, use Docker Engine and grant your account socket access
according to your organization's policy. Docker access is privileged; do not expose its
socket, make it world-writable, or run debugealo as administrator to mask configuration errors.

`doctor` exits 0 when all checks pass, 1 for an unavailable/denied Docker daemon,
and 2 for invalid configuration. It reports Python, configuration, platform, local endpoint,
connectivity, permissions, and Docker server version. A successful API read proves access
to that operation, not authorization for every Docker API operation.

Configuration is optional. See [configuration](docs/configuration.md) and
[architecture](docs/architecture.md). Usage after installation requires no Internet.
Dependency installation and example image builds may require downloads.

## Not available yet

`debugealo` and `debugealo tui` open the terminal dashboard; see the
[keyboard workflow](docs/tui.md). The future `gui` command is not registered.
Python's current breakpoint workflow is documented
in [code projects](docs/code-projects.md#debug-python-with-the-same-profile).

The installed distribution, primary Python package and command are named `debugealo`. The
legacy `debugpilot` command, `python -m debugpilot`, and `debugpilot.*` imports remain
supported aliases; both import paths resolve to the same implementation and state. Existing
`debugpilot` configuration and workspace data paths are intentionally unchanged.

### Upgrade an existing checkout

After switching an existing checkout from the `debugpilot` distribution to `debugealo`,
reinstall the local project while preserving packages outside the lockfile:

```console
uv sync --inexact --frozen --reinstall-package debugealo
```

The rename makes the new and old distributions share the `debugpilot` console-script name;
a regular sync during the transition can remove the old script. Reinstalling the current
project restores both commands. `--frozen` uses the checkout's existing lockfile and
`--inexact` retains unrelated installed tools. No configuration, profiles, or breakpoints
need to be renamed, copied, or migrated.

Read [Docker integration](docs/docker.md) for limits, logging-driver support, and reconnect semantics.

## Known issues

- F5 runs have shown an intermittent test failure whose cause is not established.
- One `NoneType` integer error was reported in the dashboard and has not recurred or been explained.
- Windows has not been rechecked since Python attach and the F5 and F9 changes.

## Tests

`uv run pytest` needs Docker and, for the Go debugging tests, Delve available as `dlv`
(see [Go debugging](docs/go-debugging.md)). Those tests fail rather than skip when Delve is missing.

## License

[MIT](LICENSE)
