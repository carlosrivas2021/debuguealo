# Compose launch profiles
Objective: reusable workspace launch profiles and automatic registration of existing Compose projects, without executing Docker during discovery.
Branch: codex/compose-launch-profiles; delivery: exception-ok (user requested one commit and push directly to origin/main); forecast: 1200–1800 authored lines; runner: .venv/Scripts/python.exe -m pytest -m "not integration".

## Specs

### S1 — Reusable configuration and already-running services
> Planteame una solucion donde pueda resolver eso de la mejor manera ux, tambien imagina que esos servicios ya estaban arriva de manera manual, no pasaron por aqui, pudieramos tener un json para configurar el string parecido a vscode con el debug

Provide named, structured profiles in the opened workspace's `.debugpilot/launch.json` (not VS Code's own launch.json). Support the proposed `version`, `configurations`, `name`, `type: docker-compose`, `projectName`, `cwd`, ordered `files`, optional `projectDirectory`, and `up` build/detach/forceRecreate fields. `${workspaceFolder}` is an explicitly supported variable; do not execute shell strings or guess shell variables. Existing containers remain observable without a complete profile.

### S2 — Automatic registration without starting through the app
> Incluso si lo levante directo deberia generar un rergistro en ese launch

Latest user clarification supersedes automatic file writes:
> Lo se pero no me gusta UN Segundo json, apliquemos esa forma como vs code

Detect Compose projects in memory and expose dynamic configurations immediately without writing any discovery JSON. Saved configurations live only in the opened workspace's `.debugpilot/launch.json` and take precedence over detections. Inventory refresh never rewrites this user-owned file. Provide an explicit Save Configuration action independent of Preview/Confirm or Docker execution. Because the TUI does not host the user's editor model, saving may atomically create a missing launch.json; if it already exists, show/copy the configuration for the user to add in their editor, never replace it. Keep bounds, workspace path guards, malformed-document preservation and no second discovery JSON.

### S3 — Preserve nested Compose semantics
> Yo tengo unos ejemplos en donde lo levanto asi
> cd user/proyect
> s=scratchpad
> docker compose -f local/agents/docker-compose.yaml -f $S/agents.ports.yaml up --build -d --force-recreate
>
> esto esta contemplado dentro del codigo para resolverlo?

Separate process/file-resolution `cwd` from Compose `projectDirectory`. New profiles default the latter to the first Compose file's parent (native Compose semantics), or use the explicitly configured value. Resolve ordered relative files from cwd. Preserve the existing global version-1 compose-projects.json cache without destructive migration, and preserve existing confirmation, target pinning, cancellation and current-run log behavior. Configured up flags apply to launch; r remains restart and Shift+R remains rebuild/recreate. No changes to Docker endpoint/credential isolation or shell execution.

### S4 — Authorized implementation
> Implementa lo que mencionas aqui

Integrate profiles into existing Compose UI and r/Shift+R, with named profile selection, actionable pending/error status and explicit preview/confirmation. A detected complete profile should avoid re-entering its paths. Provide concise documentation and deterministic regression coverage. Do not create a generic shell interpreter or automatically start/stop/rebuild real containers during discovery. Real-daemon verification is read-only except the explicitly authorized stop scenario in S6, and does not mutate the workspace registry used by the user.

### S5 — Explicit container and group stop
> No tengo opcion de stop un contenedor o un grupo de contenedores deberiamos agregarlo de una vez

Add an explicitly confirmed stop action for the selected container or all active containers in the selected Compose group, independent of launch-profile completeness. Pin the exact target identities before confirmation; never silently retarget after selection/inventory changes. Stop does not remove containers, images or volumes, and is distinct from cancelling a local CLI. Prevent overlapping operations, expose partial failures honestly, and refresh inventory/log view after completion. Automated tests use fake Docker boundaries; S6 owns any actual stop proof.

### S6 — Authorized real stop verification
> Si puedes detener los servicios actuales, asi confirmas que se esta mandando bien la info

After fake-boundary tests, inspect the actual local inventory and pin the active `dp-demo-catalog` api/worker IDs from the ongoing conversation. Only those confirmed local targets may be stopped for the requested runtime verification. Do not stop other projects, delete containers/volumes, restart services automatically or infer authorization for remote Docker. If the actual target set is ambiguous or differs materially, ask before mutation. Report observed after-state and partial/unknown outcomes honestly.

## Tasks

- T1 | S1–S2 | delegated direct: initial storage/discovery; inline ownership correction | functionally verified: ephemeral detection and create-only explicit save; native review blocked | commit: ec5f93b | bounded store/model, user-owned launch, no discovery file, focused tests and docs.
- T2 | S3 | delegated direct: parallel independent Compose semantics unit | implemented; parent focused 49 passed, 1 skipped across T1/T2 | commit: ec5f93b | optional project directory/up settings, revalidation and compatibility tests/docs.
- T3 | S1–S6 | inline: dependent UI/inventory integration | revised dynamic/saved UI functionally verified; S6 conditional proof unavailable (zero active targets); native review blocked | commit: ec5f93b | named detections/saved profiles, explicit Save/Copy, compact form and pinned stop controls; full suite and scoped independent correction recheck passed.
- T4 | S5 | delegated direct: independent stop backend parallel to parent integration | implemented; focused 9 passed, existing stream/service 36 passed | commit: ec5f93b | bounded confirmed stop API and per-target partial/unknown results; parent owns UI integration and S6 actual stop.

## Log

### L1 — Original implementation request
Implementa lo que mencionas aqui

### L2 — Accepted prior requirement
Incluso si lo levante directo deberia generar un rergistro en ese launch

### L3 — Initial evidence and route
Baseline ace132b46fd85cfd6c0c628c8db21d0651910092; tree clean before this feature. Existing store only caches name/workspace/files globally; ComposeProject conflates workspace with project-directory. ContainerInfo retains bounded Compose labels. Explorer mapped integration points; parent spot-checked constructors, inventory ownership and dialog behavior. T1 and T2 have disjoint edit surfaces and independent deterministic tests, so they launch together. T3 depends on both and stays inline. Opened workspace defaults to the application's launch working directory, with an injectable explicit workspace for tests; tests must isolate generated launch files.

### L4 — Safety and verification
Risk items 2 (untrusted metadata/path and registry write guards), 3 (shared Compose command defaults), and 4 where async inventory/selection integration changes. Required own RED→GREEN, differential old-command checks, one feature-end independent verifier, native assessment/review only when due. No source-mutating normalizers after candidate freeze. No remote push/PR/merge authorization is inferred from the previous delivery.

### L5 — User scope extension, 2026-10-29
No tengo opcion de stop un contenedor o un grupo de contenedores deberiamos agregarlo de una vez

Added S5/T4; existing valid T1/T2 outcomes remain. Stop backend edits are disjoint from launch storage/Compose semantics and parent UI edits. T3 also wires S5 confirmation without executing real Docker stop during verification.

### L6 — User real-Docker authorization, 2026-10-29
Si puedes detener los servicios actuales, asi confirmas que se esta mandando bien la info

Added S6 and reopened only T3 runtime verification scope. Parent will inspect/pin current dp-demo-catalog api/worker IDs before executing any actual stop; automatic discovery and workers remain non-mutating against real Docker.

### L7 — Observed local inventory, 2026-10-29
Read-only DockerService.list_containers against the established local named pipe returned zero active (running/paused/restarting) containers. No stop mutation was attempted. Do not start services without additional authorization; the real running-to-stopped transition proof is pending while no active target exists.

### L8 — Integration and observed checks
T1/T2 parent spot check: 49 passed, 1 skipped. T3 initial UI RED: 3 failures (missing workspace integration); stop UI RED: 3 failures (missing stop controls). Integration focused cases pass. A realistic stopped-group scope probe reproduced selecting a stopped group stopping an active sibling before correction; fixed by reusing `_group_members()` (same visible area), with pinned IDs and no real Docker actions. Pre-correction full suite: 197 passed, 1 skipped, 3 integration tests deselected in 95.78s. Final focused and independent feature-end checks follow; symlink creation is unavailable under both available Windows execution contexts and remains an explicit skip.

Profiles use a fixed `.debugpilot/launch.json` destination in the opened workspace. Discovery preserves original member order and explicit Compose project directory; process cwd and dotenv files are bound separately. A discovery path fingerprint promotes user-edited mappings to manual profiles rather than refilling them. Legacy Compose call defaults and the version-1 global routes cache stay unchanged. Malformed launch JSON blocks profile-backed Compose operations but not logs or explicit stop. No live Docker container was started, stopped or deleted.

### L9 — Independent verification and scoped correction
Independent isolated suite: 198 passed, 1 symlink-capability skip, 3 integration tests deselected in 133.54s. Nine legacy CLI cases and eight Compose action/scope combinations match baseline outputs/arguments. S1/S4/S5 passed; one S2/S3 blocker reproduced stale discovered environmentFiles after its label disappeared. Added generated/manual regression cases (RED 1 failed, 1 passed), made absent optional environment metadata explicit as an empty list, and scoped independent recheck closed the original blocker (3 passed in 1.47s). Final own targeted check: 29 passed, 1 skip; parent spot check: 10 passed in 14.62s. All 50 Python files pass Ruff format/check. A second real inventory read still reported zero active containers (two catalog containers exist), so S6 running-to-stopped proof is not claimed.

### L10 — Delivery boundary pending human decision
The implementation is approximately 2.2k authored lines including tests, docs and this log. One cohesive slicing pass identifies T1 store/discovery, T2 Compose semantics, T4 stop backend, then T3 dependent UI integration. T1 and T3 exceed the 400-line review guideline because their validation/confirmation logic must travel with tests and docs; no cosmetic compression or artificial split is applied. Before the first work-unit commit, request a feature-branch-chain strategy with a size exception for those two cohesive units; no remote publish or PR creation is authorized. Native assessment identified known item-2 scope and requires explicit untracked declaration (inventory digest sha256:b97c2ffefc9688e3953c79b0a76c3b2d01650fa073c5797914a95e14067002b4); review has not started for this feature. Pending native consent remains separate from the delivery choice.


### L11 — Explicit direct-main delivery request, 2026-10-29
Haz el commit y el push a main

User explicitly requested one commit and direct push to origin/main rather than the proposed four-commit chain. Keep this integrated delivery together with its tests and docs; no force push. Existing functional and independent proof stands; native review consent remains separate. Real stop transition proof remains unavailable because both observed inventories had zero active targets.

### L12 — User-authorized corrections, 2026-10-29
Corrige lo corresponde

Native review reported a compare-to-replace editor-save race and a registration count exceeding the reader's 128-entry limit. Its transaction stopped with unknown causality for another finding, without offering native correction authority. This new user request authorizes local fixes, not disabling review or claiming approval. Reopen T1; reproduce and fix the count invariant inline. A bounded read-only explorer confirmed that a noncooperating editor cannot be protected by a portable compare-and-replace or advisory lock; the safe user-owned launch plus app-owned discovery registry design requires a product decision before changing the fixed storage contract. Risk: items 1 (existing user data), 3 (shared registry contract), 4 (editor concurrency). Final independent verification follows the completed correction, not the partial count fix.

Count regression RED: two failures and one passing 127-to-128 boundary. Registration now preflights all additions before editing or writing and the write boundary repeats the 128-entry guard; rejection preserves existing bytes and creates no registry for an oversized initial batch. GREEN store suite: 15 passed, 1 symlink-capability skip in 0.75s; focused Ruff checks pass. A disposable public-register probe reproduced the later race: register returned True while a save injected inside os.replace was lost. No real workspace registry or Docker was changed. Product decision pending: separate user-owned launch.json from app-owned automatic discoveries, merged for the UI, rather than allowing automatic replacement of an editable file. No native lifecycle action, commit, or push followed the terminal review.


### L13 — VS Code-style ownership accepted, 2026-10-30
Lo se pero no me gusta UN Segundo json, apliquemos esa forma como vs code

Updated only S2 and reopened T1/T3. Route: inline dependent storage/UI behavior; no independent writer units. Discovery is ephemeral; explicit user save creates only a missing launch.json atomically with no-clobber. For an existing file the save UI offers JSON to copy into the user's editor, not unsafe replacement. No sidecar registry or new cache. Preserve existing manual/saved profiles, Compose confirmation and Stop semantics. Observe RED for discovery-no-write, concurrent-save preservation, and explicit save without Docker; run focused tests and independent verification (Risk items 1, 2, 3, 4). Native terminal review authority is untouched; no approval is claimed.

Observed storage RED: two failures (discovery wrote a file, explicit save API absent). Explicit-save UI RED: missing Save Configuration action. GREEN: 22 passed, 1 symlink-capability skip in 5.21s for storage and launch UI. A compatibility batch exposed four failures: adding a new action row pushed Preview below the viewport, and detection hints could mask explicitly selected legacy/session routes. Save now shares the existing action row; explicit routes win over ephemeral hints while saved launch profiles retain precedence. Targeted legacy/group/profile regressions: 26 passed, 1 skip in 16.68s. All 51 Python files pass Ruff check after formatting. Existing-editor copying, create-if-absent race, file absence during discovery, saved precedence, disappearance on a fresh store, count bounds and Save-without-Docker are covered. Final independent verification pending; no commit/push or native lifecycle mutation.

Independent full suite before final export correction: 207 passed, 1 symlink-capability skip, 3 integration tests deselected in 98.04s; Ruff check and format of 51 files passed. Three independent ownership/export probes found two new Save blockers: copy mode stayed document-shaped after a raced editor creation, and exporting a loaded profile substituted the workspace boundary for its nested process cwd. Both probes became repository regressions (RED two failures), and one correction batch fixed both. Own focused storage/UI: 24 passed, 1 skip in 6.59s. Scoped independent recheck of original two probes plus repository regressions: four passed in 3.27s; both blockers closed. Parent reran the two regression nodes successfully. No additional broad sweep or actual Docker mutation. Risk: items 1 (editor data), 2 (workspace guards), 3 (shared routing/export semantics), 4 (concurrent creation).

Needs your decision: local implementation is verified, but the prior native transaction remains terminal `native_stop_required` with an inconclusive finding; no native correction or acknowledgement continuation was offered. Review mode remains enabled. No commit or push has been made, and terminal review authority is not bypassed or silently reset.


### L14 — Explicit publication decision, 2026-10-30
Haz el push

The user explicitly requests delivery of the corrected and independently verified implementation to origin/main. Native review remains inconclusive and enabled; no approval, acknowledgement, reset, or review bypass is claimed. Its terminal transition governs that lifecycle, not ordinary Git delivery. Publish one integrated Conventional Commit as already requested, with tests and docs, by normal fast-forward push only. Runtime Stop proof remains unavailable (no active targets); the symlink-capability test is skipped and integration tests are excluded. Rollback boundary: revert this complete integrated feature commit to remove workspace launch profiles and Stop controls without changing the preceding current-run log fix. All T1–T4 implementation is included in this delivery commit; its exact identity is recorded in the session delivery evidence after creation.

### L-final — Status reconciliation (2026-11-10)

T1–T4 shipped in ec5f93b (feat(tui): add dynamic launch profiles and confirmed stop controls), as the previous Log entry anticipated. S6 runtime Stop proof remains unavailable as recorded. 2026-11-10 status reconciliation: tests/unit with -m "not integration" on main 783a6b8: 864 passed, 1 deselected, 0 failed (1032s). Integration tests not run (need real Docker). No native review approval is claimed.
