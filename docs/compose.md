# Explicit local Compose actions

Compose actions can start, restart, recreate, or rebuild either one selected service or an
entire named project. They interrupt running applications. They are never run by
discovery, log streaming, or tests against the user's containers.

Use [the terminal file browser](starting-projects.md) to start a project without
existing containers, or configure an existing selection below. Browsing is local;
Preview resolves the selected file identity with read-only Compose config inspection.

## Configure and confirm

1. Select a trusted workspace directory and its explicit Compose project name.
2. Choose one or more Compose YAML files **in override order**, for example
   `compose.yaml`, then `local.yaml`. Files must be readable inside that workspace.
3. Choose the service or whole-project scope and review the command before confirming.

Launch profiles may also pin a separate Compose project directory and explicit `up`
options. Relative Compose files still resolve from the workspace; the project directory
controls Compose's default project-name and `.env` lookup semantics. New profiles can
choose `build`, `detach`, and `forceRecreate`; values are booleans, not command-line
fragments. Profile `up` options affect starting only. The `r` shortcut remains restart,
and `Shift+R` remains rebuild-and-recreate. Existing saved projects without these
fields keep their original workspace-based project directory and start defaults.

After a successful operation, the app remembers that project's workspace and ordered
Compose files in a local JSON file, including across app restarts. On a selected
service or project, `r`
prepares restart and `Shift+R` prepares rebuild/recreate using those files. A small
inline bar shows the target with Confirm and Cancel buttons; the dashboard remains
visible and no screen is pushed. Enter confirms the focused Confirm button;
Escape cancels without executing. The command is
available as the bar's tooltip. Files
are revalidated for each preview and again before execution. Projects not configured
previously show a reminder instead of changing screens. `Ctrl+O` opens the editable form
to change the remembered file selection.

While an inline operation runs, Cancel becomes Stop CLI. It cancels the local CLI,
not the running services or Docker-side changes, and does not roll back. Completion
is reported as a notification; the inventory and logs stay visible throughout.

Dashboard logs are limited to the current execution using Docker's `StartedAt`,
including when selecting a service again or retrying with `Ctrl+R`. A successful
inline restart/rebuild refreshes the inventory and reconnects the affected view,
discarding its previous buffer while retaining logs from the new startup. Recreated
containers are resolved using their Compose service identity. Selecting another
service while an operation runs does not retarget that selection on completion.
Failure or cancellation does not clear the current view. Docker's stored history
is not deleted, and CLI log history remains unchanged.

### Saved project locations

`compose-projects.json` lives next to the existing user `config.toml`:
`%LOCALAPPDATA%\debugpilot\compose-projects.json` on Windows, or the platform's
user configuration directory on other systems. It is strict JSON, not VS Code
`launch.json` or JSON with comments. No environment values, credentials or YAML
contents are saved. A typical document is:

```json
{
  "version": 1,
  "projects": [
    {
      "name": "dp-demo-catalog",
      "workspace": "C:/projects/debugealo/examples/multi-project/catalog",
      "files": ["compose.yaml", "local.yaml"]
    }
  ]
}
```

The app writes absolute paths and preserves override order. Relative file paths
in a manually edited document resolve within its absolute workspace. Close the
app before editing this file. Removing a project entry makes the next app session
ask for configuration again; it does not stop or remove containers.

Malformed, unsupported-version, unreadable or oversized documents are reported,
not silently overwritten. Missing Compose files require configuration again.
Saving uses a temporary file and atomic replacement; a save failure leaves the
successful Docker operation unchanged and keeps the configuration in memory for
the current session. Simultaneous app instances use last-writer-wins configuration.

| Action | Result |
| --- | --- |
| Start project | `up -d --pull never`; no forced recreation or forced rebuild. |
| Restart | Restart existing containers with their existing environment configuration. |
| Recreate | `up -d --force-recreate --pull never`; apply changed Compose/environment configuration. |
| Rebuild and recreate | Add `--build` before recreating containers. |

Selected-service actions use the **Compose service name**, not the container name,
and `--no-deps` prevents starting or restarting dependencies. Whole-project actions
apply to services selected by Compose's project configuration. Multiple `-f` files
are passed in the supplied order; later files can override earlier configuration.

**Restart does not reload changed environment variables.** Use recreation after
changing `environment`, `env_file`, or applicable `.env` interpolation values.
See [Docker's restart documentation](https://docs.docker.com/reference/cli/docker/compose/restart/)
and [Compose up](https://docs.docker.com/reference/cli/docker/compose/up/).

## Trust and limitations

- Only a local Unix socket or Windows named pipe is used. Ambient Docker contexts,
  `DOCKER_HOST`, Compose overrides, and credential environment variables are not inherited.
  Windows system installation locations (`ProgramFiles`, `ProgramData`) are retained
  so Docker can discover its installed CLI plugins, without reading the user's config.
- Docker CLI with Compose v2 must already be installed. DebugPilot does not install it.
  A private empty Docker config prevents reuse of registry credentials; private image
  pulls and credential-dependent builds may therefore fail.
- The workspace is **trusted executable configuration**, not a sandbox. Dockerfiles,
  Compose hooks, mounts, `.env` files and build contexts can run code, expose local
  files, or use the network. `--pull never` prevents service-image pulls; it does not
  prevent Dockerfile builds from accessing networks or obtaining base images.
- Confirmation binds the explicit target and Compose file contents. If those YAML
  files change before execution, create a new preview. Other workspace files can
  still change; stop concurrent edits when running an operation.
- Recreating containers replaces their writable layers. Mounted volumes are not
  explicitly removed, but important data must already be stored/backed up correctly.
- Commands use literal arguments without a shell. Output is combined and bounded
  to 256 KiB, is not persisted by this service, and may contain build/application
  secrets. Review before copying or sharing it.
- Nonzero exit codes are preserved. Timeout (10 minutes by default) or cancellation
  stops/reaps the owned local CLI/plugin process tree, **not a transactional rollback**:
  Docker daemon builds
  or partially changed containers may remain. Inspect the project before retrying.
- On Windows, a helper establishes a kill-on-close Job Object before starting Docker;
  on POSIX the helper runs in a new session/process group. If Windows cannot establish
  containment, it fails before launching Docker. This prevents descendant-held stdout
  from defeating cancellation; it is not a sandbox for trusted project code.
