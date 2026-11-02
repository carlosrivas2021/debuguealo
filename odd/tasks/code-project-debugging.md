# Code projects: run and debug
Design-first roadmap; runtime implementation is not authorized by this document alone.
Status: design/code-project-debugging/01-sidebar-console.html selected; design and documentation complete. Runtime stages are planned, not started. Directions 02 and 03 remain alternatives, not implementation targets.
Current authorization override: the “Implement this” selection is documentation-only. Do not implement production code; runtime stages will be taken in another session.

## Specs
S1. Project centralization and source access: "Ahora quiero agregar otra area para controlar el debug del codigo, teniendo en cuenta que quiero centraliar en una aplicacion todos los proyectos de codigo, en donde pueda ejecutar el codigo, como lo hace vscode en el area de debug, pero quiero tener dos funciones uno con debug y otro si debug, se puede abrir en cualquier carpeta y tambien tener un launch.json para esos proyectos, donde por ejemplo pueda tener npm run dev o python main.py o go main.go y poder tener acceso al codigo para elegir donde coloccar el break si lo necesito, armemos un plan para ir desarrollando esto paso a paso."
S2. Separate configuration: "Quiero otro launch.json, porque si crece demasiado puede ser complicado, tener separado el launch.json de contenedores y de proyectos de codigo"
S3. One profile, two modes: "No es necesario 2 si lo corro con F5 es sin debug y shift f5 es con debug por ejemplo"
S4. Design and continuity: "Crea primero el diseno tambien, para luego con engram ir tomando cada tarea"
S5. Preserve existing visual style: "C:\Users\Usuario\Pictures\Screenshots\Captura de pantalla 2026-11-02 185647.png Este es el actual mantengamos lo mas que podamos el estilo"
S6. File breakpoint tree: "the breakpoints puede estar dentro de la flecha dentro de los archivos como un tree"

## Tasks
T0 | S1-S6 | done: three alternatives delivered; 01 refined to screenshot and canvas comments, checked, selected and documented; runtime implementation deferred by explicit user instruction | route: design artifacts only | commit: none
T1 | S1-S2 | planned: register explicitly selected project folders and validate dedicated code launch profiles without changing container configuration | route: decide at implementation | commit: none
T2 | S1,S3 | planned: run one profile without debug using F5; interactive output, exit status, stop/re-run and child-process cleanup | route: decide at implementation | commit: none
T3 | S1 | planned: browse project source and mark file/line breakpoints; visibly distinguish pending from verified | route: decide at implementation | commit: none
T4 | S1,S3 | planned: debug Python using Shift+F5 on the same profile; stop at breakpoint, inspect stack/variables, step and continue | route: decide at implementation | commit: none
T5 | S1,S3 | planned: add server-side Node debugging; distinguish npm launcher from the debug target | route: decide at implementation | commit: none
T6 | S1,S3 | planned: add Go debugging and a real breakpoint walkthrough | route: decide at implementation | commit: none
T7 | S1 | proposed follow-up, not committed scope: multiple sessions, persistent breakpoints, attach and recovery | route: product decision after core flow | commit: none

## Acceptance and scope
- T0: three self-contained HTML alternatives using design/system.md; independent container/code areas, dedicated code launch action, one selected profile and both shortcuts; simulated behavior clearly labeled; no production changes.
- T1: two explicitly chosen roots can be registered independently of application cwd; malformed code profiles do not disable container profiles. Exact new launch path/schema remains a proposal until implementation design.
- T2: run and stop npm, Python and Go sample processes; verify exit status, missing executable and process-tree cleanup through public interfaces. Correct executable Go example: `go run main.go` (user's original preserved in S1).
- T3: open source and toggle a line breakpoint without modifying the file; pending indicators are not presented as debugger confirmation.
- T4-T6: run a real per-language example, hit a breakpoint, inspect a variable and continue; unavailable adapter must produce an actionable error, not silent fallback to run mode.
- Initial design assumes the existing terminal UI; HTML boards illustrate TUI layout, not a desktop frontend decision. Source read-only first is a recommendation, not an explicitly requested editing restriction.
- Existing container launch location and behavior remain unchanged. Suggested separate location: `projects/launch.json` beside the existing central launch file; not created by this work.
- No duplicate run/debug profile required. Debugging still needs adapter-specific target information. Arbitrary npm scripts and browser debugging are not automatically supported.
- Stop shortcut is not decided; the mockups use a button rather than inventing another binding.
- No production code, installations, process execution, migration, commit or push is authorized by this design task.

## Selected design handoff — documentation only
Chosen: `design/code-project-debugging/01-sidebar-console.html` — Compact terminal tree + docked console. Tokens: `design/system.md`. Alternatives: `02-focus-workspace.html`, `03-session-workbench.html`; do not implement or merge their layouts.

### Visual and interaction contract
- Preserve current compact terminal appearance: single-row header/actions, compact profile/root/command strip, existing palette and monospace renderer, thin separators, approximately 22% left tree, expansive main pane, docked output and bottom shortcuts. HTML pixels are illustrative, not Textual cell dimensions.
- Persistent Containers / Code selector. Switching views preserves context and must not start/stop execution. Contextual launch action opens the corresponding configuration; existing container configuration remains separate and unchanged.
- Sidebar heading is only `PROJECTS` (comment uvsvpb4j). Project selection uses row highlighting, not a fake expansion arrow (qt7wb8kc, ysbjs35u). Clicking or keyboard activation selects; F5 runs and Shift+F5 debugs the same profile.
- A real file expansion control contains the source action and breakpoint line entries (07e2mchp). Breakpoints belong to files beneath the selected project, not a separate BREAKPOINTS section. Pending and adapter-verified states must be distinguishable; removed breakpoints disappear from the tree.
- Main pane: source, line markers, current execution location; subordinate call stack and variables; output below. Stop targets only the relevant area's session.
- Simulation notices, fixed sample roots, sample states and fake transcripts are design scaffolding, not production implementation. Do not claim adapter success without actual adapter evidence.

### Mapping to real stack (implementation guidance, not work performed)
- Reuse Python/Textual composition and shared style tokens in `src/debugpilot/tui/app.py` and `styles.tcss` for compact area navigation and layout. Preserve existing container widgets/actions rather than replacing the Docker area with mock HTML.
- Follow existing storage patterns in `src/debugpilot/storage/launch_profiles.py`, but isolate code profiles and validation; exact code schema/path is still to be finalized. No automatic migration.
- Evaluate `src/debugpilot/terminal/session.py`, `tui/terminal_view.py` and `tui/execution_console.py` for reuse; a managed local process is not merely text typed into an interactive shell. Keep lifecycle, process cleanup and language adapters outside widgets.
- Implement file/breakpoint domain state independently of the displayed tree. Never copy the self-contained artboard HTML/JS into the production Textual stack.

### Next session
Read Engram context and `odd/code-project-debugging/tasks`, then this whole document; reconcile latest canvas comments before changing code. Begin T1 (selected folders, independent code configuration and the minimum area-navigation scaffold), then T2 through T6 with tests and evidence per task. T7 remains optional proposed scope. Reassess sizing/risk and create an authorized feature branch before any large implementation work-unit commits. No commits or pushes were made for this design handoff.

### Verification boundary
HTML structure, JavaScript syntax and worker simulated interactions were checked. Last file-tree change received HTML/tree and syntax checks only; actual browser interaction/rendering, visual contrast and real Textual keyboard behavior are unverified. Native ASSESS was unavailable for these untracked design artifacts; do not treat this as review approval. Future production work requires its own functional tests and applicable review.

## Log
L12. Canvas selection received: "Implement the design artboard design/code-project-debugging/01-sidebar-console.html". Per explicit L11 exception this records the selected design only, not authorization to implement runtime code. gentle_design implement registered 01 as chosen. Handoff documented above; no implemented status submitted because production is unchanged. T0 complete, T1-T6 deferred to another session at user's request; 02/03 remain alternatives.
L13. Resolved canvas comments preserved: uvsvpb4j "Solo con projects es suficiente"; qt7wb8kc "No entiendo como funciona el cambiar de proyecto"; ysbjs35u "Que va dentro de la flecha?"; 07e2mchp "the breakpoints puede estar dentro de la flecha dentro de los archivos como un tree". Final design uses PROJECTS heading, highlighted project selection and expandable file breakpoint tree.
L11. Explicit handoff override: "Voy a darle al boton implementar pero en este caso solo documentalo, y luego en otra sesion vamos implementadolo por pasos". When the canvas selection arrives, record the actual chosen artboard and document its handoff only. Do not treat the button as runtime implementation authorization. Future session must reconcile plan and Engram before task-by-task implementation.
L1. Original request: "Ahora quiero agregar otra area para controlar el debug del codigo, teniendo en cuenta que quiero centraliar en una aplicacion todos los proyectos de codigo, en donde pueda ejecutar el codigo, como lo hace vscode en el area de debug, pero quiero tener dos funciones uno con debug y otro si debug, se puede abrir en cualquier carpeta y tambien tener un launch.json para esos proyectos, donde por ejemplo pueda tener npm run dev o python main.py o go main.go y poder tener acceso al codigo para elegir donde coloccar el break si lo necesito, armemos un plan para ir desarrollando esto paso a paso."
L2. "Quiero otro launch.json, porque si crece demasiado puede ser complicado, tener separado el launch.json de contenedores y de proyectos de codigo"
L3. "No es necesario 2 si lo corro con F5 es sin debug y shift f5 es con debug por ejemplo"
L4. "Perfecto, donde registraste el plan para irlo desarrollando por partes"
L5. "Crea primero el diseno tambien, para luego con engram ir tomando cada tarea"
L6a. User question: "Como cambiarias entre si estoy en la vista de dockers y la de promgraming?" Proposed visual answer: persistent Containers / Code tabs, preserve selection and console context, show active-session indicators, contextual launch.json action; switching areas never executes or stops processes. This is a design proposal, not a new runtime requirement approved by the user.
L6. Existing design/system.md and previously implemented dashboard direction reviewed. Additive designs: design/code-project-debugging/01-sidebar-console.html (recommended), 02-focus-workspace.html, 03-session-workbench.html and design.json. No chosen artboard; all remain alternatives. Previous dashboard unchanged.
L7. Worker reported passing HTML/manifest/token checks, Node syntax checks and simulated-DOM interactions (area context retention, separate launch previews, shortcuts and breakpoint controls). Initial checker failures were Windows encoding and an overly broad color regex; corrected checks passed. Parent read back manifest and recommended board; git diff --check passed. Supplemental parent Python-to-Node check failed with Windows cp1252 UnicodeEncodeError; not retried, and does not supersede worker's successful UTF-8 syntax evidence. No browser rendering, measured contrast or real TUI keyboard verification performed.
L10. Screenshot-aligned refinement delivered in 01-sidebar-console.html and its manifest metadata only. Header/actions reduced to compact rows, left tree 22%, broad source/log workspace, subordinate inspection and docked output, bottom shortcut row. Worker reports passing UTF-8 structural/palette/font/JS and simulated-interaction checks; alternatives 02/03 hashes unchanged. Parent read back board and manifest and observed git diff --check exit 0; canvas refreshed. No browser-rendered visual/contrast/keyboard validation. All functionality remains illustrative; no production changes or commits. Await user visual choice/feedback before implementation.
L9. User refinement: "C:\Users\Usuario\Pictures\Screenshots\Captura de pantalla 2026-11-02 185647.png Este es el actual mantengamos lo mas que podamos el estilo". Parent read supplied screenshot. Reopen T0 only; preserve dense terminal rows, existing palette, left tree, large main pane, bottom shortcut bar. Refine 01 only; 02 and 03 remain alternatives unchanged.
L8. Canvas opened with gentle_design for code-project-debugging. Native ASSESS unavailable for untracked artifacts (explicit scope declaration needed); no native review started. This is design-only, not production behavior. Next decision: user chooses or comments on an artboard before runtime implementation.
