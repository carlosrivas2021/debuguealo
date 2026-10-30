# Terminal dashboard

Run `uv run debugpilot` or `uv run debugpilot tui` to open the local Docker dashboard.
Use `uv run debugpilot tui --config path/to/config.toml` for explicit settings. Docker
connection status is shown separately from saved launch configuration state.

The dashboard keeps containers and logs in terminal-style panels, with a near-black
background, muted separators, compact one-line actions, and visible keyboard focus.
On smaller terminals the panels stack vertically; the same keyboard shortcuts apply.

## Launch profiles

The primary sidebar lists saved profiles from the central user-configuration
`launch.json`, using each profile's `name`. Central profiles require their own explicit
`workspaceFolder` root. Explicit local-workspace callers retain the
`.debugpilot/launch.json` compatibility location. If none are saved, choose
**Open launch.json** to create or edit that file in an editor. Opening the file is
explicit; startup and Docker inventory refresh never create or rewrite it.

Choose a profile and use **Play / Recreate** to apply its Compose files, or **Build +
Recreate** when code changed. Both actions require confirmation. `r` previews Play /
Recreate; `Shift+R` previews Build + Recreate. There is no plain Restart action in the
TUI. `Ctrl+O` or `Ctrl+N` opens `launch.json` directly; neither key opens a Compose file
picker or starts a service. Editing stays in the same terminal: DebugPilot suspends
the dashboard, runs `nano` (falling back to `vi` when nano is not installed), and
restores the TUI after the editor exits. The launch profiles are reloaded on return.
There is no editor timeout and no external graphical window. Install `nano` or `vi`
on PATH; if neither is available, the TUI displays an actionable warning.
In nano, use Ctrl+O, Enter to save and Ctrl+X to return. In vi, use `:wq` to save
and return, or `:q!` to discard your edits.

The profile's display `name` is for people. Containers link by the configured Compose
`projectName` label, so profiles can have names different from their Docker projects.
Each saved profile row contains indented, selectable children for its matching actual
containers. Profiles remain listed when they have no matching containers. When two
profiles share a Compose project, each retains its own child rows. Selecting a profile
shows combined project logs; selecting a child shows that container's logs and Stop
acts on that actual container. Play and Build + Recreate continue to act on the owning
saved profile. Incomplete or invalid profiles remain visible as pending and must be
fixed in `launch.json` before they can run.

## Active containers and logs

The separate **View active containers** area shows only actual Docker inventory that
is not owned by any saved profile, grouped by Compose project; standalone containers
remain separate. Containers with a matching saved-profile `projectName` appear under
their profile instead and are not duplicated below. Unowned containers do not grant
permission to run arbitrary Compose actions. Choose an actual container or project in
the lower area to inspect logs or explicitly stop visible targets. **Show all** reveals
stopped containers both under their owning profiles and in a distinct inactive area for
unowned containers. Group stop actions use the visible project's active members; hidden
siblings are not silently included.

Selecting a saved profile links log selection to active containers with the matching
`projectName`; it does not rename them to the profile's display name. A project-level
selection combines that project's service logs, while selecting a container isolates
its logs. Selection survives inventory reorder and refresh; if a target disappears, an
unrelated stream is not opened automatically.

| Control | Effect |
| --- | --- |
| `r` | Preview Play / Recreate for the selected saved launch profile. |
| `Shift+R` | Preview Build + Recreate for the selected saved launch profile. |
| `s` | Confirm stopping the selected visible container or project group. |
| `Ctrl+O` / `Ctrl+N` | Edit the central (or explicitly selected local) `launch.json` with nano or vi. |
| `Ctrl+L` | Focus logs. |
| `Ctrl+R` | Retry the selected log stream after EOF or an error. |
| `q` | Exit. |

Recreate and Build + Recreate interrupt running services. They use explicit profile
files and never interpret shell command strings or shell variables. See
[Compose safety and limits](compose.md) and [container stop](container-controls.md).

## Log display limits

The in-memory log buffer is limited to 2,000 entries and 2 MiB. Pausing can lose older
entries when those limits are reached. Copy depends on terminal clipboard support.

## Not implemented yet

DAP, breakpoints, source navigation, variables and stepping are not implemented. This
dashboard does not pretend to debug source code or provide a desktop editor.
