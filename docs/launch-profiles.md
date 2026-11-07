# Workspace Compose launch profiles

debugealo shows detected Compose configurations immediately, including services started
outside the app. These dynamic profiles live only in memory. By default, saved configurations live in the stable central `launch.json` beside
debugealo's user `config.toml`, independent of the process working directory. Profiles
in this central file must declare an existing absolute `workspaceFolder`; that directory
is the confinement root for `cwd`, Compose files, `projectDirectory`, and
`environmentFiles`. The optional explicitly selected `LaunchProfileStore(workspace=...)`
compatibility mode still uses `<workspace>/.debugpilot/launch.json` and confines paths
to that workspace. The old local file is not automatically loaded, moved, or deleted by
central mode. Discovery does not create or rewrite launch files.

## Quick path

1. Start debugealo from any directory; the default application uses the same central launch file.
2. From the empty welcome, choose **Open launch.json** to edit the central configuration with nano or vi in the same terminal.
3. On first open, debugealo creates the file only if it is missing, with an empty `configurations` array. Add profiles with an explicit `workspaceFolder`. Only explicit local-workspace mode generates a catalog starter when that workspace contains the real example.
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
      "workspaceFolder": "/path/to/project",
      "source": "manual",
      "cwd": "${workspaceFolder}",
      "files": ["local/agents/docker-compose.yaml", "agents.ports.yaml"],
      "up": {"build": true, "detach": true, "forceRecreate": true}
    }
  ]
}
```

`workspaceFolder` is required in central mode and must name an existing, non-symlink absolute directory; it is the project root, never inferred from cwd or Docker metadata. `cwd` is where relative file paths are resolved, while `${workspaceFolder}` expands to that profile's root. `projectDirectory` is optional; without it, Compose uses the first file's parent. No shell command, inherited environment, or other variable expansion is performed. `up` flags are optional strict booleans; omitted values remain unspecified.

## Limiting a profile to some services

Add the optional `services` array to run a profile against only part of its Compose
project, for example a shared database defined beside application services:

```json
{
  "name": "Shared database",
  "type": "docker-compose",
  "projectName": "platform",
  "workspaceFolder": "/path/to/project",
  "cwd": "${workspaceFolder}",
  "files": ["local/platform/docker-compose.yaml"],
  "services": ["database"],
  "up": {"build": true, "detach": true, "forceRecreate": true}
}
```

**Play / Recreate** and **Build + Recreate** append the names to `docker compose up`
(and to `restart`), so only those services are created or recreated. Compose still starts
their declared `depends_on` dependencies; `--no-deps` is not added. The confirmation
shows the service names instead of "all services". **Stop** on the profile row pins only
active containers whose Compose service is listed; selecting an individual child
container still stops just that container.

`services` must be an array of unique Compose service names (letters, digits, `.`,
`_`, `-`, starting with a letter or digit); anything else leaves the profile pending.
Names are checked against `docker compose config --services` before any mutating
operation, and an unknown name fails without running `up`. Omitting the field or
setting `"services": []` keeps acting on every service in the project. Containers of unlisted services still
appear under the profile because grouping uses the Compose project label.

## Refreshing AWS credentials

Profiles whose containers read AWS session credentials from a dotenv file can declare
where those credentials go:

```json
{
  "name": "Worker",
  "type": "docker-compose",
  "projectName": "worker",
  "workspaceFolder": "/path/to/project",
  "cwd": "${workspaceFolder}",
  "files": ["local/worker/docker-compose.yaml"],
  "awsCredentials": {
    "envFiles": ["local/.env.aws"],
    "profile": "dev"
  }
}
```

`envFiles` lists 1–16 files, resolved like `files` (relative to `cwd`, confined to
`workspaceFolder`). A file may be missing, but its directory must exist. `profile` is
an optional AWS CLI profile name; without it the default credential chain is used.
An invalid `awsCredentials` object leaves the profile pending.

Press **a** in the dashboard, or run `debugpilot credentials refresh`, to refresh every
saved profile that declares `awsCredentials`. debugealo runs
`aws configure export-credentials --format process [--profile NAME]` without a shell,
once per AWS profile, and writes each distinct file once. Only `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN` are replaced (or appended); other lines
such as `AWS_REGION` are kept. A stale session token is removed when the CLI issues
none. Files are written atomically with mode 0600 and symlinks are refused. Credential
values are never printed, logged or written to temporary files outside the target
directory.

If the SSO session expired, the AWS CLI fails and debugealo asks you to run
`aws sso login` (with `--profile` when set); it never opens a browser itself. Containers
keep their old environment until recreated, so after a successful refresh the dashboard
offers **Recreate** for the refreshed profiles that have running containers. Confirm to
recreate them one after another, or press Escape to skip. The CLI command only lists
the profiles to recreate.

## Discovery and safety

Discovery groups containers by Compose project label, not container ID. Saved profiles
for a project take precedence; discovery never edits their fields. Docker directory,
configuration-file, and environment-file labels are used only in explicit local-workspace
mode and only when they resolve inside that workspace. Central mode never trusts labels
to choose an external root; profiles without a saved root remain pending. Missing,
conflicting, stale, inaccessible, or escaping paths remain pending. A profile load or
discovery operation never executes Docker Compose.

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

The default application uses the central configuration location; each central profile
selects its own project root. Explicit local-workspace mode remains available to callers.
debugealo suspends its TUI and runs `nano`, or `vi` if nano is unavailable, in the
same terminal without a shell. It waits for the editor to exit, restores the dashboard,
and reloads the profiles. Install nano or vi on PATH, including on Windows; the tool
does not use graphical editors or system file associations. A nonzero editor exit
or an unavailable editor is reported in the TUI. See [terminal controls](tui.md)
for save and exit shortcuts.

`environmentFiles` may list project-local dotenv files when an existing Compose
project reports explicit `--env-file` metadata. Their paths, not contents, are stored;
the preview binds their content hashes and refuses execution if they change. They remain
Compose interpolation inputs; they are not replaced by direct container environment
values in `overrides`.

## Direct service environment and port overrides

Add the optional `overrides.services` object to the relevant `docker-compose` entry
in `configurations`, not to the launch file's top level. It changes values for named
Compose services without editing the source YAML. The service must exist in the
service list reported by Compose; an unknown service is rejected before any
mutating Compose operation. The fragment below shows only the override field; keep the
entry's existing `type`, `projectName`, `cwd`, and `files`:

```json
{
  "overrides": {
    "services": {
      "api": {
        "environment": {
          "MODE": "production",
          "TOKEN": "replace-with-your-value"
        },
        "ports": ["9000:80"]
      }
    }
  }
}
```

`environment` must map string keys to string values. Supplied keys replace or add those
keys, and all other service environment values are preserved. Values are literal JSON
strings: `$` is passed literally to the container rather than expanded by this profile
format. This does not change Compose interpolation inputs such as `environmentFiles`.
There is no `null` deletion syntax, shell expansion, or implicit interpolation.

A supplied `ports` array replaces the service's entire published-port list; it does not
append to the original list. Use `"ports": []` to clear all published ports. Port
entries must be strings in the format accepted by Compose. Unknown override keys and
invalid value types make the profile pending with a generic validation message.

Overrides are rendered into a private Compose override file (mode 0600, removed after
the run) that is passed as the last `-f`, after the profile's own files. Compose merges it
normally: `environment` keys merge by name and `ports` uses `!override`, so the canonical
model is never serialized and re-read. This keeps source-only syntax such as interpolated
`build.ssh` entries working, which Compose cannot round-trip through `config --format json`.
Service names are checked against `docker compose config --services` before any mutating
operation. The source YAML and launch JSON are not rewritten. The override file contains
plaintext environment values temporarily, so avoid committing secrets in launch files
and protect workspace files. Preview arguments and profile representations do not show
the values. Recreate (or Build + Recreate) applies changed container environment and
ports; Restart alone cannot change the existing container configuration. The `!override`
tag requires Docker Compose 2.24.4 or newer.

## Independent external profiles

For the example project root `/path/to/project`,
add these three objects independently to the central file's `configurations` array. Keep
`workspaceFolder` set to that exact root for each profile:

```json
[
  {"name":"Agente","type":"docker-compose","projectName":"local-agente","workspaceFolder":"/path/to/project","cwd":"${workspaceFolder}","files":["local/agente/docker-compose.yaml"]},
  {"name":"MCP","type":"docker-compose","projectName":"local-mcp","workspaceFolder":"/path/to/project","cwd":"${workspaceFolder}","files":["local/mcp/docker-compose.yaml"]},
  {"name":"Conversation","type":"docker-compose","projectName":"local-conversation","workspaceFolder":"/path/to/project","cwd":"${workspaceFolder}","files":["local/conversation/docker-compose.yaml"]}
]
```

Each profile previews and confirms independently. **Play / Recreate** and **Build +
Recreate** are the existing actions; there is no plain-start action. Merely reading or
opening this configuration does not run Docker or create project files.
