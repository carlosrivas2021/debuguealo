# Workspace Compose launch profiles

DebugPilot shows detected Compose configurations immediately, including services started
outside the app. These dynamic profiles live only in memory. Your saved configurations
live in the single `.debugpilot/launch.json` at the opened workspace root. Discovery
does not create or rewrite this file and does not create a second discovery JSON.

## Quick path

1. Open the project directory that owns the Compose files.
2. Let inventory refresh. Open **Ctrl+O** or **Open Compose** to choose a detected or saved profile. Incomplete metadata remains pending; it is never used to launch anything.
3. Choose **Save Configuration** when you want to keep a profile. Review its JSON and name, then select **Create launch.json** if the file is absent.
4. If the file already exists, use **Copy JSON** and add the configuration object to its `configurations` array in your editor. DebugPilot does not replace an existing editor file. The next refresh picks up your changes.

Saving or copying never runs Compose. Preview and Confirm are separate actions.
Dynamic profiles are rediscovered from inventory rather than restored from a cache.

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

Detected entries are ephemeral; saving makes a manual configuration. Local mappings,
custom fields and launch flags in saved profiles are never reconciled from Docker.
Conflicting detection metadata stays pending until a trusted mapping is supplied.

The application opens the directory from which it was launched as its workspace.
Run DebugPilot from the repository that owns the Compose files. `Ctrl+O` shows named
profiles for the selected project; **Open Compose** / **Ctrl+N** offers all profiles
in the workspace, including profiles with no running containers. **Edit paths** expands
the form. Merely choosing a profile does not launch Docker: Preview and Confirm are
still required. `r` and `Shift+R` use the chosen profile for restart and rebuild.

`environmentFiles` may list workspace-local dotenv files when an existing Compose
project reports explicit `--env-file` metadata. Their paths, not contents, are stored;
the preview binds their content hashes and refuses execution if they change.
