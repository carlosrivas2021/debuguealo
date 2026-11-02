---
name: add-launch-service
description: "Trigger: agregar servicio, nuevo servicio, configurar launch.json, add service, add launch profile. Add a DebugPilot Compose profile without replacing existing profiles or starting containers."
metadata:
  version: "1.0"
---

## Activation Contract

Use for saved DebugPilot Compose profiles or service overrides in `launch.json`, not VS Code debugger configurations. Adding a profile does not define a new Compose service.

## Hard Rules

- Read the references before editing.
- Locate the central file through `LaunchProfileStore().path`, beside `config_path()`. Never assume `.vscode/launch.json`.
- Obtain explicit authorization naming absolute paths before accessing files outside the project; otherwise return a proposed fragment only.
- Preserve existing profiles, unknown fields and ordering. Never overwrite malformed JSON or use create-only `save_configuration()` to append.
- Never run Compose mutations, pull images, modify source YAML or store secrets for this task.

## Decision Gates

| Situation | Action |
| --- | --- |
| “Service” could mean a profile or YAML service | Clarify before writing. |
| Central mode | Require an existing absolute `workspaceFolder`; never infer it from Docker labels. |
| Explicit local-workspace mode | Use `<workspace>/.debugpilot/launch.json`; do not migrate files. |
| Missing project identity, root, files or conflicting entry | Ask; do not fabricate paths or overwrite profiles. |
| Existing service environment/ports | Use `overrides.services.<actual-compose-service>`, not a top-level service field. |

## Execution Steps

1. Inspect the authorized file. Confirm the project root, ordered Compose files and `projectName`. Keep display `name` distinct; match the Compose project label when linking running containers.
2. Append one version-1 `configurations` object using the referenced example: `name`, `type: "docker-compose"`, `projectName`, central-mode `workspaceFolder`, `cwd: "${workspaceFolder}"`, `files`. Resolve files relative to `cwd`, confined to the root. Omit unrequested optional fields.
3. If requested, use strict-boolean `up` flags. Override environment values are literal strings; supplied `ports` replaces all published ports and `[]` clears them. Keep `environmentFiles` interpolation inputs separate.
4. Validate proposed JSON with `LaunchProfileStore.load()`, `profiles()` and `resolve()` in isolated temporary state using authorized paths. Reject pending/unresolved profiles; verify intended files and preservation of unrelated fields. Respect 128-profile and 256-KiB limits. Do not report secrets.
5. Recheck original bytes before saving; stop on concurrent edits. Review the minimal diff and reload the dashboard. Runtime changes require separately authorized Recreate or Build + Recreate.

## Output Contract

Report launch path, profile/project identity, resolved files, checks, unchanged runtime state and missing authorization. Proposal-only work returns a fragment without writing.

## References

- [Schema and examples](../../../docs/launch-profiles.md)
- [Validation API](../../../src/debugpilot/storage/launch_profiles.py)
- [Central path](../../../src/debugpilot/storage/config.py)
- [Dashboard controls](../../../docs/tui.md)
