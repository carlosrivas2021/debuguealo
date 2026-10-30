# Central launch configuration and external project roots
Objective: decouple launch profiles from the process working directory while retaining project-local path guards.
Branch: codex/launch-owned-sidebar; delivery: ask-on-risk, no push authorized; forecast: 300–400 authored changed lines; runner: /tmp/debugealo-launch-grouping/venv/bin/python.

## Specs

### S1 — Stable central configuration
> Pero la idea es que yo pueda abrir debugpilot desde su propia carpeta no depende de donde estoy ubicado
> si

Confirmed proposal: "Un **`launch.json` central de DebugPilot**." Default launch configuration must not change when the process cwd changes. Use the existing application user-configuration directory for a stable launch.json. Read-only startup must not create or migrate files. Preserve the existing explicitly selected workspace interface for compatibility; document its distinction from default central mode.

### S2 — Explicit external project roots
Confirmed proposal: "Cada perfil indica la carpeta de su proyecto externo." and "Sus rutas Compose se resuelven desde esa carpeta."

A saved profile explicitly declares its project root; resolve cwd, Compose files, projectDirectory and environmentFiles against that root, and pass that root into existing Compose confinement. Never derive external trust from Docker labels. Preserve rejection of paths escaping the selected root, unsupported variables, invalid options and unsafe root symlinks/reparse points. No automatic moving or overwriting of existing launch files.

### S3 — Independent example profiles
> Ok, tengo el ejemplo en una carpeta externa /mnt/c/Users/Usuario/Documents/Development/test-docker, ayudame a configurar cada uno como si lanzara esto individual
> docker compose -f local/agente/docker-compose.yaml up -d
> docker compose -f local/mcp/docker-compose.yaml up -d
> docker compose -f local/conversation/docker-compose.yaml up -d

Confirmed proposal: "Agente, MCP y Conversation siguen siendo perfiles independientes."

Document three central profiles for the exact example root and relative Compose files. Actual declared project names observed read-only: local-agente, local-mcp, local-conversation. Keep current Play/Recreate semantics disclosed; this change does not add a plain-start action or execute Docker.

## Tasks

- T1 | S1–S2 | delegated single coherent storage/config behavior with tests and docs | done | commit: 994964c | RED invalid-root exception; GREEN storage/TUI 34 passed and parent spot-check 25 passed. Risk: items 2/3.
- T2 | S1–S3 | delegated same worker integration and example documentation | done | commit: 994964c | Central Open, read-only startup and explicit external-root preview/confirmation passed; three profiles documented.
- T3 | S1–S3 | parent assessment, independent scoped verification and local work-unit commit | done | commit: 994964c | Independent verifier S1–S3 met, 51 passed; native assessment unavailable; no push or live Docker changes.

## Log

### L1 — Original request and confirmation
User: "Pero la idea es que yo pueda abrir debugpilot desde su propia carpeta no depende de donde estoy ubicado"
Parent: "Te propongo:\n- Un **`launch.json` central de DebugPilot**.\n- Cada perfil indica la carpeta de su proyecto externo.\n- Sus rutas Compose se resuelven desde esa carpeta.\n- Agente, MCP y Conversation siguen siendo perfiles independientes.\n\n¿Querés que lo cambie con ese modelo de configuración central y carpetas externas por perfil?"
User: "si"

### L2 — Exploration incident and design
HEAD 801d992. Existing unstaged tracked differences are CRLF-only and local .debugpilot/ is untracked; preserve them. Read-only explorer mvvc56f6-7-58la stalled at CodeGraph (0 turns, 1 tool call) and was cancelled; no retry or second explorer. Parent direct reads established config.config_path() already uses platformdirs, default_workspace() currently uses Path.cwd(), and ResolvedLaunch.workspace already feeds ComposeProject guards. Default central location will be config_path().parent / launch.json. Explicit per-profile workspaceFolder is the root; do not relax ComposeProject checks. Tests use isolated state; never create actual user config or mutate real containers. Existing full-suite Compose cancellation failure is independently confirmed baseline behavior, not permission to suppress other failures.

### L3 — Initial implementation and bounded correction
Writer mvvd86re-8-wv5m reported S1–S3 implemented: focused 56 passed, full suite 27 failed / 219 passed / 3 deselected; only one failure is known baseline Compose cancellation. Format check also reported test_launch_file.py. Native assess unassessable due undeclared ambient untracked paths; escalation item 2 requires independent verification. Parent observed default test fixture patches obsolete default_workspace; also requested invalid root become per-profile Pending and central inventory discovery stay usable with self.workspace=None. Correction mvvdmta0-9-8yz4 is limited to these same feature failures, proper central test isolation and Open launch proof. No test suppression or real Docker operation.

### L4 — Writer correction and parent spot-check
Correction completed: isolated central config_path fixture replaces obsolete default_workspace patch; test profiles explicitly declare their root. Invalid roots are per-profile Pending; central Docker discovery stays ephemeral/pending without path trust. Focused 34 passed. Full nonintegration suite: 248 passed, 1 known baseline Compose cancellation failure, 3 deselected. Earlier focused grouping-selection assertion failed once, exact rerun and later suite passed; retained as intermittent evidence, not silently green. Ruff lint and formatting 14 files clean. Parent spot-check central/storage 25 passed in 3.52s and Ruff passed. Independent verifier mvvdyrka-a-pxmx running on S1–S3, focused scope only. Native assessment remains unavailable due undeclared ambient untracked paths; escalation item 2 requests independent verification.

### L5 — Independent verification and local delivery
Verifier mvvdyrka-a-pxmx independently reported S1–S3 met with no functional/security blockers: 34 public tests and 17 additional isolated probes, 51 passed in 2.32s; compileall exit 0. One scratch-probe expected-message assumption was corrected, not implementation. Workspace/copy launch_profiles.py SHA-256 matched 2d74c7295451e364fa2ecafe78ad7a91c69e38ae30af2907ff0e01f15f798e77. Exact probe source retained under /tmp/debugealo-launch-grouping/verify/central/check.qOvVTI/work/tests/unit/test_central_verifier.py; no actual user-config or example access. Clarified Quick path: central mode creates an empty array, catalog starter is explicit-local only. Commit 994964c contains the coherent behavior, tests and docs (337 additions / 37 deletions), preserving unrelated CRLF-only worktree differences by preparing normalized index blobs for selected files only. Postcommit native assessment over base 801d99281f5b08642aeff3ed709e495b1b5b09d4 remained unassessable due undeclared ambient untracked paths; no native review approval or lineage was created. Independent security verification completed as required. No push, actual editor launch or live Compose operation. Windows reparse handling inspected but not executed on Windows; no typecheck configured. One known baseline Compose cancellation failure and one earlier intermittent grouping assertion remain explicitly disclosed.
