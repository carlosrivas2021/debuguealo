# Terminal dashboard

Run `uv run debugpilot` or `uv run debugpilot tui` to open the local Docker dashboard.
Use `uv run debugpilot tui --config path/to/config.toml` for explicit settings. Docker
connection status is shown separately from saved launch configuration state.

The dashboard presents saved profiles, their containers, and unowned Docker inventory
in one scrollable project tree on the left, with logs and selected-container details in the main pane,
and Compose execution output in a separate docked console. The same persistent dock
contains the Host Bash PTY pane; the container shell occupies the right-hand logs area.
Mounting either pane never starts a shell. Native Textual
widgets use the existing near-black palette, muted separators, compact controls, and
visible keyboard focus. Sidebar, logs, Compose output, and terminal remain separate.
Unchanged inventory refreshes preserve the tree's scroll position and selection;
changes to displayed ports, state, or rows still update the inventory.
Column widths account for cell padding and vertical-scrollbar space, including after resize.
The sidebar reserves its scrollbar gutter so scrolling does not shrink the tree's viewport.
On desktop terminals the 48-column sidebar prioritizes project/service names over
port and state columns. Narrow terminals retain the stacked layout.

Text filter, search, and severity share one compact toolbar. Search still supports
Ctrl+F, Enter, and N; filtering and log ingestion are unchanged. Table headers,
selection, controls, and footer use the existing dark project palette.
The lower console starts completely hidden, leaving all rows available to the dashboard.
Press `O` from the project tree to show it. When shown, the Compose console displays an
empty-state hint until a real execution produces output.
Inactive terminal panes occupy no rows. `C` replaces the right-hand logs with the
selected container's shell without opening the lower console; `H` shows Host Bash below.
Only one session is active: switching between C/H closes the previous session first.
Press `O` or **Hide output · O** to hide the entire console and return all its rows to
the dashboard. Focus returns to the project tree; press `O` there to restore the dock.
Hiding does not clear output or close an active session. Explicitly opening a terminal
with `H` also reveals the console. `O` does not hide the right-hand container shell.

## Containers / Code

Use the top **Containers** and **Code** buttons to switch without starting or stopping
processes. Code lists registered project folders and command arguments; container
shortcuts are inactive there. Ctrl+O / Ctrl+N edits the active area's launch file.
**Open code launch.json** opens the separate central code configuration directly.
In Code, **F5** or **Run (F5)** runs the selected profile without debug. Type in its
terminal; **Escape** returns focus to profiles. **Stop** ends only the Code process
tree. A running profile survives area changes; repeated F5 does not restart it.
See [code project execution](code-projects.md) for the schema and current limits.

## Launch profiles

The primary sidebar lists saved profiles from the central user-configuration
`launch.json`, using each profile's `name`. A valid inactive profile shows `Stop` as its
available group action; active profiles show their active count, and invalid profiles
remain `Pending`. Central profiles require their own explicit
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
restores the TUI after the editor exits. After a successful editor exit, valid JSON is
formatted with two-space indentation while preserving field order and unknown fields. Invalid
JSON is left byte-for-byte unchanged and the TUI reports its line and column; fix it in the
editor and reopen the file. Duplicate object keys and nonstandard numeric constants are
rejected without rewriting. Formatting is also refused unchanged if it would exceed the
256 KiB launch-file limit. Formatting uses an atomic replacement and checks for concurrent
changes immediately before replacement. The launch profiles are reloaded on return.
There is no editor timeout and no external graphical window. Install `nano` or `vi`
on PATH; if neither is available, the TUI displays an actionable warning. Launch profiles
may also declare per-service direct environment and published-port overrides; see
[launch profile overrides](launch-profiles.md#direct-service-environment-and-port-overrides).
In nano, use Ctrl+O, Enter to save and Ctrl+X to return. In vi, use `:wq` to save
and return, or `:q!` to discard your edits.

The profile's display `name` is for people. Containers link by the configured Compose
`projectName` label, so profiles can have names different from their Docker projects.
Each saved profile row contains indented, selectable children for its matching actual
containers. Profiles remain listed when they have no matching containers. When two
profiles share a Compose project, each retains its own child rows. Selecting a profile
shows combined project logs; selecting a child shows that container's logs and Stop
acts on that actual container. A child appears under its owning profile and is not
repeated in the unowned groups of the same tree. Press `Space` on a profile or project
group to collapse or expand its children; selection stays on that group. `r` previews Recreate and `Shift+R` previews
Build + Recreate for the selected saved profile; both preserve confirmation and target
pinning. Redundant sidebar Play/Recreate buttons are hidden. Incomplete or invalid
profiles remain visible as pending and must be fixed in `launch.json` before they can run.

## Active containers and logs

The same **Projects / containers** tree also shows actual Docker inventory not owned
by any saved profile, grouped by Compose project or under a standalone group. It displays assigned `public_port` bindings (including bracketed IPv6 host
addresses), not private-only exposed ports. **Show all** reveals stopped containers
under their owning profiles and unowned groups without creating another inventory table.
Group stop actions use the visible project's active members; hidden siblings are not
silently included. Press `D` on a selected container to view its actual name, image,
state, Compose project/service, and published ports; `Esc` returns to logs.

Selecting a saved profile links log selection to active containers with the matching
`projectName`; it does not rename them to the profile's display name. A project-level
selection combines that project's service logs, while selecting a container isolates
its logs. Selection survives inventory reorder and refresh; if a target disappears, an
unrelated stream is not opened automatically.

| Control | Effect |
| --- | --- |
| `r` | Preview Recreate for the selected saved launch profile. |
| `Shift+R` | Preview Build + Recreate for the selected saved launch profile. |
| `s` | Confirm stopping the selected visible container or project group. |
| `C` | From the project tree, show `/bin/sh` for the selected running container in the logs area. |
| `H` | With the project tree focused, open host Bash in the explicit local workspace or the selected central profile's validated working directory. |
| `D` | Show details for the selected actual container. |
| `Esc` | In the terminal, return focus to the current left table; otherwise return from details or cancel a pending confirmation. |
| `O` | Hide/show the entire docked console; when hidden, restore it from the project tree with `O`. |
| `Ctrl+O` / `Ctrl+N` | Edit the central (or explicitly selected local) `launch.json` with nano or vi. |
| `Ctrl+L` | From outside a focused shell, show and focus container logs. |
| `Ctrl+R` | Retry the selected log stream after EOF or an error. |
| `q` | Exit. |

`C` pins the currently selected running container (including a profile child) and uses the
configured Docker endpoint, or the existing platform default. With an explicit local
workspace, both terminals keep using that canonical workspace. In central-profile mode,
both use the selected profile's working directory, resolved by the same workspace/path
validation as Compose. `H` requires no container selection. Missing or invalid profile
contexts are refused; no arbitrary current-directory fallback is used.
Both require a focused project tree; invalid workspace/target contexts are refused.
Startup failures appear in the corresponding terminal area. There is no PowerShell fallback. Once a terminal
is focused, typed keys and control keys—including `Q`, `D`, `S`, `R`, and `O`—belong to
the shell; `Ctrl+C` is sent to it and `Esc` returns focus to the left table. The terminal
keeps its opened target when inventory selection changes and is never reopened by refresh.
For C, **Logs** (or Esc, then Ctrl+L) returns to logs without ending the shell.
Press C on the same selected target to restore that pinned session; changing selection
alone never retargets it. Both terminal areas offer **Close terminal** to end the session
or cancel a pending startup; closing C restores logs. Switching views joins prior cleanup,
including when a pending switch is cancelled. Startup runs
outside the app message handler so the close control remains responsive; close and app
shutdown cancel and join any pending opening task before releasing the session.
No real shell is started by app startup,
widget construction, inventory refresh, or the Compose-output toggle.

Recreate and Build + Recreate interrupt running services. They use explicit profile
files and never interpret shell command strings or shell variables. Compose execution
output streams literally to the dedicated Compose console, with start and exit
summaries even when the CLI emits no output. The latest operation output is retained in
memory with its project/profile identity and restored after same-profile refresh; it is
not shown when another project/profile is selected, is not persisted, and does not
fabricate application logs. A concrete Docker `No such image` diagnostic offers inline
**Download and retry** and **Cancel** controls. Cancel is the safe default, including
Enter while Cancel is focused; only explicit Download consent retries the original
pinned action once for that selected profile. Other failures show their output without
a download option. Closing, cancelling, refreshing, or changing the profile never
implicitly grants consent. The transcript stays separate from application logs, retains
the latest operation for the selected profile in memory, and can be hidden/restored
without clearing it. See [Compose safety and limits](compose.md) and
[container stop](container-controls.md).

## Log display limits

The in-memory log buffer is limited to 2,000 entries and 2 MiB. Pausing can lose older
entries when those limits are reached. Copy depends on terminal clipboard support.

## Not implemented yet

Code supports read-only source navigation and session-local **pending** line
breakpoints nested beneath files. See [source browsing](code-projects.md#browse-source-and-mark-pending-breakpoints).
DAP, verified breakpoints, variables and stepping are not implemented. This dashboard
does not pretend to debug source code or provide a desktop editor.
