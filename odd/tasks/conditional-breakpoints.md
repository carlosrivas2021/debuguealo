# Conditional breakpoints and logpoints
Objective: let a breakpoint carry a condition and/or a log message (logpoint) across the editor, persistence and every debug adapter. Branches: feat/conditional-breakpoints-{1-storage,2-adapters,3-ui}; base: b27581a.
Delivery: ask-on-risk -> user chose stacked-to-main (2026-11-09): PR1 storage (T1), PR2 adapters (T2), PR3 UI + docs (T3-T4); runner: uv run pytest.

## Specs
S1. User request verbatim: "si" to "¿Arrancamos con eso?", where the proposal was "**breakpoints condicionales y logpoints**. Debugpy y Delve ya los soportan vía DAP, así que el trabajo es sobre todo de UI: cómo cargás la condición o el mensaje sobre la línea, y cómo se marca en el editor."
S2. Approved design verbatim ("si" to "¿Aprobás este diseño?"): "**Shift+F9** sobre una línea abre un diálogo chico con dos campos: **Condición** (por ejemplo `user_id == 42`) y **Mensaje de log** (por ejemplo `pedido {order.id} recibido`). Si el mensaje está cargado, es un logpoint: no frena y escribe en la salida de debug."
S3. Approved design verbatim: "**F9** sigue igual: breakpoint simple."
S4. Approved design verbatim: "**En el gutter:** `●` simple, `◆` condicional, `◇` logpoint."
S5. Approved design verbatim: "**Lenguajes:** Python, Go, Node y los dos attach (Python y Go)." and "debugpy y Delve soportan `condition` y `logMessage` nativamente en DAP, y en Node CDP acepta `condition`. Los logpoints en Node se hacen como VS Code: una condición que hace `console.log(...)` y devuelve `false`."
S6. Approved design verbatim: "Agregar condiciones y logpoints cambia ese modelo en todas las capas, **incluido el formato guardado en disco**. Eso es lo delicado: lo voy a hacer compatible hacia atrás, para que un `breakpoints.json` viejo siga cargando igual." Acceptance: a file without conditions is written byte-identical to today; options are stored only on entries that have them.
S7. Out of scope verbatim: "hit count ("frenar en la vuelta N"). Se puede sumar después con el mismo diálogo."

## Tasks
T1 | S6 | done (uncommitted): BreakpointOptions + breakpoint_options(); load_options(); save(marks, options=None) writes "options" only on entries that have them; RED 13 failed -> GREEN store/persistent/compat 25 passed, Ruff 0 | route: inline | Risk: item 1 (persisted format) | commit: pending chain strategy
T2 | S2,S5 | todo: Python/Go DAP sessions, Python/Go attach and Node send condition/logMessage at start and on update; existing calls without options unchanged | route: inline | Risk: none expected (additive optional parameter) | commit: -
T3 | S2-S4 | todo: Shift+F9 dialog, gutter glyphs, tree labels, options in BreakpointsChanged/snapshot wired to CodeDebug start/update, persistence | route: inline | commit: -
T4 | S1-S7 | todo: docs (code-projects, tui keyboard, README) and final verification | route: inline + independent verifier (item 1) | commit: -

## Log
L1. 2026-11-09 user: "si" (start conditional breakpoints and logpoints), then "si" approving the design quoted in S2-S7.
L2. Exploration: a breakpoint is a line number in every layer. source_browser.py keeps `_marks: dict[(root, path), set[int]]`; F9/gutter toggles; BreakpointsChanged(root, path, lines) -> code_debug.breakpoints_changed -> session.set_breakpoints(path, lines); breakpoint_snapshot(root) -> session.start(profile, intent). storage/breakpoints.py rejects any entry key other than root/file/lines, so older versions reject a file that contains options; options are therefore written only on entries that have them. Delve, debugpy: DAP `condition`/`logMessage` with `{expr}` interpolation. Node: CDP setBreakpointByUrl `condition`.
L3. Design for compatibility: every API gains an optional `options` argument; current signatures and return values stay unchanged.
L4. 2026-11-09 user chose "Stacked to main (Recommended)" for the PR chain: storage -> adapters -> UI + docs.
