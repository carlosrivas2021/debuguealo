# Launch-owned sidebar
Objective: make saved launch configurations the primary TUI workflow, with a VS Code-style welcome and separate active-container inventory.
Branch: codex/launch-owned-sidebar; delivery: ask-on-risk (user requests main publication); forecast: 900–1400 authored lines; runner: isolated temporary Python environment (see Log).

## Specs

### S1 — Empty welcome and direct launch-file opening
> Ok, vamos por partes quiero que si no hay nada se parezca a esto de vscode
> Quitemos eso de abrir compose
> Directamente manda abrir el archivo
> Abre el archivo launch.json

Show a compact welcome when no saved configurations exist, with a direct Open launch.json action rather than a Compose YAML picker/form. Remove Open Compose from the visible primary workflow. Keep Docker connection errors distinguishable from genuine empty configuration. Do not imply source debugging is implemented. Use English UI copy, consistent with the existing app.

### S2 — Basic example structure, only when missing
> Si no existe arma una estructura basica con la ruta del example

On explicit file-open only, create a missing `.debugpilot/launch.json` using the real workspace example `examples/multi-project/catalog/compose.yaml`, project `dp-demo-catalog`, cwd `${workspaceFolder}`, and supported up flags. If the opened workspace lacks that example, create an empty configurations array with actionable guidance instead of inventing runnable paths. Never replace an existing file. Open the file in an editor, not a Compose operation. No second discovery JSON or cache. Preserve existing create-only path/reparse/no-clobber safeguards.

### S3 — Saved entries own the primary list
> Luego de guardar deberia salir en la lista izquierda y permitir hacer play para reproducir restart o reforce , si no esta en ese archivo asi docker tenga contenedores arriba no los muestre que los muestre solo en la parte de abajo ver contenedores activos
> Si luego de agregar ya esta arriba el contenedor relacionarlo pero con el nombre que se puso en el archivo

The primary list contains only saved launch configurations, displayed using their `name`, including profiles without running containers. Match existing Docker containers by the explicit Compose `projectName`, never the display name; refresh after the user saves without silently retargeting operations. Unconfigured active containers appear only in a distinct lower View active containers area. Keep logs and explicit Stop available for visible actual containers; raw inventory is not permission to start/recreate arbitrary projects.

### S4 — Two execution actions, no plain restart in the UI
> Significa los 2
> La idea es simular este comando docker compose -f local/agents/docker-compose.yaml -f $S/agents.ports.yaml up --build -d --force-recreate pero no se bien para este escenario que tendria que agregar en el launch.json para que funcione
> Entonces quitemos el restart no me interesa, Lo habia entendido mal
> Recrear para tomar lo de las variables o puertos y build +recrear si toque codigo

Provide Play/Recreate (`up -d --force-recreate`) and Build + Recreate (`up --build -d --force-recreate`), including profiles whose containers do not yet exist. Remove plain Restart from the TUI's visible controls/shortcuts, not from unrelated public CLI contracts. Reuse ComposeService preview, exact target pinning, confirmation, and current-run log refresh. Preserve ordered files, separate process cwd/project directory, environment file binding and workspace guards. Never interpolate shell command strings or `$S` from JSON.

### S5 — Implementation and requested publication
> Sube los cambios a main quiero probar
> Implementalo

Implement and verify the workflow; report failures and unavailable proof honestly before ordinary Git delivery. No force push, no real container mutation during automated tests. The old native review transaction remains terminal and is not silently reset or approved.

## Tasks

- T1 | S1–S2 | delegated direct: independent explicit launch-file initialization/editor unit | implemented and independently verified; capability skips documented | commit: pending | storage API, portable editor opening, regression tests and launch docs.
- T2 | S1/S3–S4 | delegated direct: independent saved-sidebar/action unit | implemented and independently verified; compatibility migration complete | commit: pending | main/lower lists, linking, two confirmed actions, welcome and UI tests/docs.
- T3 | S1–S5 | inline integration, then independent verification Risk items 1/2/3/4 | functionally verified; delivery/review decision pending | commit: pending | editor-action seam, compatibility checks, isolated suite and delivery evidence.

## Log

### L1 — Original implementation request
Implementalo

### L2 — Baseline and routing
Baseline ec5f93b10d4a2c34696a0c2c2d14e2bb7424bfe8, previously published on main. Only pre-existing untracked test `tests/unit/test_tui_welcome.py` belongs to this conversation and reflects an obsolete picker proposal; T2 may rewrite it. Two bounded writers launch together with disjoint surfaces: T1 storage/editor and T2 app/sidebar/actions. They share an explicit interface: `LaunchProfileStore.ensure_launch_file() -> Path` creates only if missing; `open_launch_file(path: Path)` requests an external editor without shell interpolation. T2 imports the opener lazily from `debugpilot.tui.launch_file`; T1 does not edit app.py. Existing saved profiles are `store.profiles()` filtered by `not profile.dynamic`. Reuse existing ComposeService, `_select`, stream ownership, confirmation and Stop; do not duplicate Docker operations. Parent owns Git and shared integration. Technical artifacts English.

### L3 — Environment and verification
The shared Windows .venv and bundled Python currently lack project/test dependencies. Parent is preparing an independent temp environment with uv sync --locked, never deleting or rebuilding .venv. Workers wait for its exact interpreter path before RED. Test scratch stays outside the workspace and workers report exact retained paths. Named risk: 1 existing launch data; 2 filesystem/editor guards; 3 shared inventory/selection/actions; 4 asynchronous refresh/pinning. Observe RED before behavior changes, GREEN after, and run one independent feature-end verifier. Native old review authority remains untouched.


### L4 — Isolated runtime and worker outcomes
Isolated locked runtime: C:/Users/Usuario/AppData/Local/Temp/debugealo-launch-ux-6b72d42498df4fd29aa06097f2576024/project/Scripts/python.exe (uv sync --locked installed31 packages, shared .venv unchanged). T1 RED missing module, GREEN24passed2symlinkcapabilityskips; source/docs only allowed surfaces. T2 RED6fail then new UI6pass; single compatibility batch37fail25pass (old workflows plus genuine cursor redraw regression). Writer bounded cursor fix still failed2cases; parent applied allowed second correction capturing visible lower-table cursor in _resize_inventory before redraw, both exact original cases passed1.70s. No third cursor correction authorized. Parent is classifying/updating only explicitly superseded UI tests while retaining raw log/Stop/selection regressions. Full suite underway once for concrete remaining-failure evidence. No commit/push/native review lifecycle operation.


### L5 — Parent integration and compatibility migration
Parent initial full nonintegration suite:37failed185passed2skipped3deselected (154.54s); failures classified by exact traces. Superseded tests now create saved profiles, select profile rows and expect recreate instead of restart, while direct legacy ComposeDialog component tests still cover file ordering, service scopes and preview/confirmation without exposing that removed main workflow. Mock external editor in UI fixtures only; opener unit tests explicitly remain real helper + mocked OS calls. No tests are skipped to hide regressions.

The parent corrected completion focus returning to the raw table (which silently changed profile/log selection), preserved the primary visible profile cursor before refresh rebuild, and made duplicate display names produce distinct row keys. Primary status shows linked active count; welcome hides empty headers/disabled action bars. Cases involving a queued focus event now wait for mount/focus in tests rather than asserting against an unmounted modal. Own final seam:14passed1symlinkskip; parent pre-verifier selection/cursor/current-run regressions7passed7.21s. Ruff check and formatting56 files clean. Independent feature-end verification next; no real Docker/editor launch, no Git delivery yet.


### L6 — Independent verification and one bounded correction
Independent isolated nonintegration suite:223passed2symlinkcapabilityskips3deselected in121.54s; Ruff check and format56files clean. One independent new-flow blocker reproduced: Escape cancelled a profile preview but focused raw inventory, selecting unrelated catalog logs. Repository regression RED1fail, fixed focus to current selection owner. Updated renamed-action modal/input guards. Layout advisories (wide truncated action labels/heading and compact welcome border) corrected with stacked wide buttons, separate heading/checkbox rows, compact welcome styling, and scrollable sidebar minimum section heights. Own layout/visibility/cancel/welcome10passed10.50s. Scoped independent recheck original probe + regression + visibility:9passed10.46s, blocker CLOSED. Four screenshot captures confirm complete labels and bounded buttons at120x40 and80x24. No new broad sweep, live Docker mutation or actual editor launch. Parent final spot check follows. All tests use fake boundaries; actual WSL editor request remains a platform-dependent manual check. Risk items1/2/3/4 remain disclosed; no native review approval claimed.
