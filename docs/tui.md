# Inspect containers and live logs

Run `uv run debugpilot` or `uv run debugpilot tui` to open the local terminal dashboard.
Use `uv run debugpilot tui --config path/to/config.toml` for explicit configuration.
Docker errors appear in the dashboard; inventory refreshes automatically every two seconds.
No daemon connection is simulated.

## Keyboard workflow

1. Use Up/Down in the grouped inventory to select a Compose project header or one
   of its indented containers. Containers without Compose metadata appear under
   **Standalone containers**.
2. Press Ctrl+L to focus logs. Arrow/Page keys scroll; Tab moves between controls.
3. Filter text or severity, or search within the retained entries. Enter in Search
   (or N when not typing) selects the next match and turns off auto-scroll.
4. Press Q outside an input to exit. Ctrl+P opens Textual's command palette.

| Control | Effect |
| --- | --- |
| Ctrl+Space / Pause | Freeze the view, not Docker or ingestion; Resume shows retained entries. |
| Ctrl+E / Auto | Toggle automatic scrolling to new entries. |
| Ctrl+K / Clear | Clear the in-memory view/buffer; never delete Docker logs. |
| Ctrl+F | Focus Search; text filtering is a separate field. |
| Ctrl+Y / Copy | Copy the selected entry using terminal clipboard support (OSC 52). |
| r | Request restart for the selected Compose service or project group. |
| Shift+R | Request rebuild and recreation for that same service or project group. |
| Ctrl+R | Retry the selected log stream after EOF or an error. |
| Ctrl+O | Configure, preview and explicitly confirm a local Compose action. |

Docker/Compose names and container states appear in the inventory. Stopped containers
use historical logs; running containers request a live stream. A state change or a
selection change closes the old stream before opening another. Logging-driver errors
are shown separately from inventory connectivity. Quit closes the UI's tasks and engine.

Selecting a project header closes the previous service's log stream and asks you to
select a service for logs. A project header never silently streams an arbitrary member.
Selection survives inventory reorder and refresh; if a selected container disappears,
its surviving project header is selected instead. If the project disappears, no unrelated
service stream is opened automatically. Identically named services in different projects
remain separate targets.

The log buffer is limited to 2,000 entries and 2 MiB. The rendered table is also bounded;
long messages can be scrolled horizontally, and embedded newlines appear as `↵`.
Pausing can lose older entries when these limits are reached. Copy depends on your
terminal's clipboard policy and is not guaranteed on every terminal.

## Compose lifecycle controls

Press Ctrl+O to configure a trusted workspace, explicit project name and ordered
Compose files (one per line). Choose the selected **Compose service** or the entire
project, then restart, recreate, or rebuild and recreate. Preview never starts a
Docker operation; **Confirm & run** does. Editing the form invalidates confirmation.
Restart keeps the existing environment; recreate applies changed environment settings.
Actions are not saved or repeated automatically. See [Compose safety and limits](compose.md).

The selected project name is prefilled and must still match the selected group.
A project header defaults to whole-project scope; a container defaults to its Compose
service, not its container name. Standalone containers do not become Compose services.

The **r** and **Shift+R** shortcuts open this same dialog with Restart or Rebuild
already selected. They never bypass **Preview** and **Confirm & run**, and typing
letters inside an input does not trigger an action. Restart preserves the container's
existing environment; Recreate or Rebuild and recreate applies updated configuration.
Use Ctrl+R, not r, when you only want to reconnect logs.

The dialog remains responsive during execution. Output appears after completion,
bounded to 256 KiB, and may contain secrets. Escape / Close stops an in-flight CLI;
it does not roll back changes already made in Docker. Press again to close afterward.

## Not implemented yet

DAP, breakpoints, source navigation, variables and stepping are T4–T5 work. Their
shortcuts report that they are unavailable; this dashboard does not pretend to debug.
The application does not provide an editor or a desktop GUI.
