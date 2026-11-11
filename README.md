<h1 align="center">debugealo</h1>

<p align="center">
  <strong>Local-first Docker debugging, right in your terminal.</strong><br>
  Watch your containers, run Compose safely, and step through Python, Go and Node code<br>
  from one keyboard-driven dashboard. No cloud, no IDE required.
</p>

<p align="center">
  <img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/docker-required-2496ED?logo=docker&logoColor=white">
  <img alt="Platforms" src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-555">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green">
</p>

---

<p align="center">
  <img alt="Containers dashboard: launch profiles, live container details, streaming logs and a confirmed recreate" src="docs/assets/containers.gif" width="900">
</p>

<p align="center">
  <img alt="Code area: setting a breakpoint, debugging a Python profile, stepping and reading variables" src="docs/assets/code.gif" width="900">
</p>

## Quick start

```console
curl -LsSf https://astral.sh/uv/install.sh | sh          # 1. install uv (once)
uv tool install git+ssh://git@github.com/carlosrivas2021/debuguealo.git   # 2. install debugealo
debugealo doctor                                          # 3. check Docker access
debugealo                                                 # 4. open the dashboard
```

> [!NOTE]
> The repository is private, so you need read access. The SSH URL uses your GitHub SSH key.
> With HTTPS credentials (for example after `gh auth login`), use
> `git+https://github.com/carlosrivas2021/debuguealo.git` instead. To update, rerun the
> install command with `--reinstall`.

uv downloads a suitable Python if you don't have one. Docker is the only other requirement.
Debugging Go also needs [Delve](docs/go-debugging.md):
`go install github.com/go-delve/delve/cmd/dlv@latest`.

## What you get

| | Feature | In short |
|---|---|---|
| 🐳 | **Containers** | Running and stopped containers grouped by Compose project, with live CPU and memory, and historical and live logs that reconnect when containers change. |
| 🚀 | **Launch profiles** | Save your Compose setups once in a central `launch.json`, then run **Play / Recreate** or **Build + Recreate** with an inline confirmation. |
| 🐞 | **Debugging** | Breakpoints, conditional breakpoints, logpoints, watch expressions, stepping and stack/variable inspection for **Python**, **Go** and server-side **Node**. |
| 🔌 | **Attach** | Connect to an existing loopback `debugpy` or Delve target, for example inside a container, without taking over its lifecycle. |
| 💻 | **Terminals** | A container shell and a host Bash docked inside the dashboard. |
| 🛡️ | **Safe by default** | Destructive actions ask first, image downloads need consent, and debug ports listen on `127.0.0.1` only. |

## Keyboard cheat sheet

**Everywhere**

| Key | Action |
|---|---|
| `Ctrl+T` | Switch between **Containers** and **Code** |
| `Ctrl+O` / `Ctrl+N` | Open `launch.json` in your terminal editor |
| `Ctrl+Left` / `Ctrl+Right` | Move focus between panes |

**Containers**

| Key | Action |
|---|---|
| `r` | Preview **Play / Recreate** |
| `Shift+R` | Preview **Build + Recreate** |
| `s` | Stop the selected container or project, after confirmation |
| `Ctrl+L` | Open logs (`D` or `Esc` closes them, `Ctrl+R` reconnects) |
| `C` / `H` | Open the container shell / host Bash |
| `O` | Show or hide the output console |
| `Space` | Collapse or expand a group |

**Code**

| Key | Action |
|---|---|
| `F5` | Run the profile, or **Continue** while paused |
| `Shift+F5` | Debug the profile |
| `F9` / `Shift+F9` | Toggle a breakpoint / add a condition or logpoint |
| `F10` / `F11` / `Shift+F11` | Step over / in / out |
| `S` | Stop the selected run |

The full workflow is in the [keyboard guide](docs/tui.md).

## Command line

```console
debugealo                      # open the dashboard (same as `debugealo tui`)
debugealo doctor               # check Python, config, Docker access and Delve
debugealo containers [--json]  # list containers
debugealo logs <name> --tail 100 [--follow]
debugealo version
```

`doctor` exits with `0` when every check passes, `1` when Docker is unavailable or access is
denied, and `2` for invalid configuration. A missing Delve is only a warning.

## Try it

| Example | What it shows |
|---|---|
| [`examples/fastapi-debug`](examples/fastapi-debug/README.md) | Attach to a Python `debugpy` target running in a container |
| [`examples/multi-project`](examples/multi-project/README.md) | Three independent Compose projects that share a network |

## Documentation

| Start here | Go deeper |
|---|---|
| [Keyboard workflow](docs/tui.md) | [Architecture](docs/architecture.md) |
| [Launch profiles](docs/launch-profiles.md) | [Docker integration and limits](docs/docker.md) |
| [Code projects and debugging](docs/code-projects.md) | [Configuration](docs/configuration.md) |
| [Compose safety and limits](docs/compose.md) | [Python](docs/python-debugging.md) · [Go](docs/go-debugging.md) debugging |
| [Container controls](docs/container-controls.md) | [Multi-project setups](docs/multi-project.md) · [Terminal](docs/terminal.md) |

## Platform notes

- **Linux:** use Docker Engine and grant your account socket access according to your
  organization's policy.
- **macOS:** use Docker Desktop.
- **Windows:** use PowerShell and Docker Desktop in Linux-container mode. Windows has not been
  rechecked since the Python attach and F5/F9 changes.

> [!WARNING]
> Docker access is privileged. Do not expose its socket, make it world-writable, or run
> debugealo as administrator to work around configuration errors.

After installation, debugealo works offline. Installing dependencies and building the example
images may download packages.

## Development

```console
uv sync --locked
uv run debugealo
uv run pytest -m "not integration"   # unit tests
uv run pytest                        # full suite: needs Docker, and Delve as `dlv`
uv run ruff check . && uv run ruff format --check .
```

The Go debugging tests fail rather than skip when Delve is missing.

<details>
<summary><strong>Coming from <code>debugpilot</code>?</strong></summary>

The distribution, package and command are now named `debugealo`. `python -m debugpilot` and
`debugpilot.*` imports still work, but the `debugpilot` command is no longer installed.
Configuration, profiles and breakpoints stay where they were, so nothing needs migrating.
To update an existing checkout:

```console
uv sync --inexact --frozen --reinstall-package debugealo
```

</details>

## License

[MIT](LICENSE)
