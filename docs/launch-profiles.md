# Workspace Compose launch profiles

DebugPilot shows detected Compose configurations immediately, including services started
outside the app. These dynamic profiles live only in memory. Your saved configurations
live in the single `.debugpilot/launch.json` at the opened workspace root. Discovery
does not create or rewrite this file and does not create a second discovery JSON.

## Quick path

1. Open the workspace in DebugPilot.
2. From the empty welcome, choose **Open launch.json** to edit the workspace configuration with nano or vi in the same terminal.
3. On first open, DebugPilot creates the file only if it is missing. When the real catalog example exists in the workspace, the starter profile points to it; otherwise the file has an empty `configurations` array.
4. Existing files, including malformed ones, are passed through unchanged so they can be repaired in the editor.

Dynamic profiles are rediscovered from inventory rather than restored from a cache.
Opening or creating the file never runs Compose.

## Version 1 shape

```json
{
  "version": 1,
  "configurations": [
    {
      "name": "Compose: catalog",
      "type": "docker-compose",
      "projectName": "catalog",
      "source": "discovered",
      "cwd": "${workspaceFolder}",
      "files": ["local/agents/docker-compose.yaml", "agents.ports.yaml"],
      "up": {"build": true, "detach": true, "forceRecreate": true}
    }
  ]
}
```

`cwd` is where relative file paths are resolved. `projectDirectory` is optional; without it, Compose uses the first file's parent. `${workspaceFolder}` is the only supported variable. No shell command, inherited environment, or other variable expansion is performed. `up` flags are optional strict booleans; omitted values remain unspecified.

## Discovery and safety

Discovery groups containers by Compose project label, not container ID. Saved profiles
for a project take precedence; discovery never edits their fields. Docker directory,
configuration-file, and environment-file labels are used only when they resolve inside
the opened workspace. Missing, conflicting, stale, inaccessible, or external paths leave
the detection pending. A profile load or discovery operation never executes Docker Compose.

The store preserves unknown JSON fields and refuses malformed, unsupported-version,
oversized, or symlinked files. Explicit creation publishes complete bytes with an
atomic create-if-absent operation: if another editor creates the file first, saving
fails without replacing it. Filesystems without this operation fail closed; copy the
JSON instead. There is no compare-then-replace window against an existing editor file.
The existing legacy global `compose-projects.json` remains separate and unchanged;
this feature adds no new cache.

The registry supports at most 128 configurations. Discovery that would exceed this
limit is rejected as a whole, leaving the existing document unchanged and readable.

Detected entries are ephemeral; saving makes a manual configuration. Saved profile names
own the primary sidebar rows, with selectable actual container children matched only by
the Compose project label. Inventory that matches a saved `projectName` is not repeated
in the lower unowned-container area. If multiple saved profiles share a project name,
each profile remains a distinct owner row with unique child identities. Local mappings,
custom fields and launch flags in saved profiles are never reconciled from Docker.
Conflicting detection metadata stays pending until a trusted mapping is supplied.

The application opens the directory from which it was launched as its workspace.
DebugPilot suspends its TUI and runs `nano`, or `vi` if nano is unavailable, in the
same terminal without a shell. It waits for the editor to exit, restores the dashboard,
and reloads the profiles. Install nano or vi on PATH, including on Windows; the tool
does not use graphical editors or system file associations. A nonzero editor exit
or an unavailable editor is reported in the TUI. See [terminal controls](tui.md)
for save and exit shortcuts.

`environmentFiles` may list workspace-local dotenv files when an existing Compose
project reports explicit `--env-file` metadata. Their paths, not contents, are stored;
the preview binds their content hashes and refuses execution if they change.
