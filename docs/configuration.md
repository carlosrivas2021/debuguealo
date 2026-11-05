# Configure local diagnostics

Configuration is optional and read-only in the current slice. Missing files use defaults.
debugealo never reads Docker CLI contexts, `DOCKER_HOST`, SSH agents, or credential stores.
Remote Docker endpoints are deliberately unsupported.

Default `config.toml` locations are provided by Platformdirs:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\debugpilot\config.toml` |
| Linux | `$XDG_CONFIG_HOME/debugpilot/config.toml`, normally `~/.config/debugpilot/config.toml` |
| macOS | `~/Library/Application Support/debugpilot/config.toml` |

```toml
event_queue_size = 256
docker_timeout_seconds = 3
# Windows default; Docker Desktop may use dockerDesktopLinuxEngine instead.
docker_endpoint = "npipe:////./pipe/docker_engine"
```

On Linux, the default is `unix:///var/run/docker.sock`. For rootless Docker set a local
socket such as `unix:///run/user/1000/docker.sock`. On macOS Docker Desktop may require
`unix:///Users/YOUR_USER/.docker/run/docker.sock`. Set your actual path explicitly.

Use `uv run debugealo doctor --config /path/to/config.toml` to select a different file.
Unknown keys, invalid types, remote endpoints, files over 64 KiB, and limits outside their
ranges are errors. Config errors do not print rejected values. Limits: queue 1–10000;
SDK request timeout 1–30 seconds. This timeout is per request; the diagnostic worker also
has an end-to-end deadline of twice that value plus three seconds for startup and cleanup.

## Upgrade an existing checkout

After upgrading a checkout that previously installed the `debugpilot` distribution, run
this from the repository root to reinstall the renamed local project while retaining
packages not listed in the lockfile:

```console
uv sync --inexact --frozen --reinstall-package debugealo
```

The transition gives the new distribution both `debugealo` and `debugpilot` console-script
entry points. Because the old and new distributions claim the same legacy script name, an
ordinary sync during the rename can remove that script; reinstalling the current project
restores it. Existing configuration stays in the `debugpilot` directories documented above.
Do not rename, copy, or remove existing configuration, launch profiles, or breakpoints.

If Docker is unavailable, start the daemon and verify the endpoint. If permission is
denied, check access under your normal account. No containers are started, stopped,
removed, or executed by `doctor`; only ping and server-version reads are performed.
