# Watch expressions
Objective: let the user keep a list of expressions per project that the debugger re-evaluates on every pause and frame change. Branches: feat/watch-expressions-{1-backend,2-ui}; base: bcc7ae8.
Delivery: stacked-to-main, reusing the user's strategy from conditional breakpoints (forecast ~550 authored lines): PR1 storage + session evaluate (T1-T2), PR2 UI + docs (T3-T4); runner: uv run pytest.

## Specs
S1. User request verbatim: "sí, sigamos con watch expressions".
S2. Approved design verbatim ("si" to "¿Aprobás este diseño?"): "**Dónde:** una sección **WATCH** nueva en el panel de debug, entre el stack y las variables. Arriba, un campo `+ Add watch expression`; abajo, una tabla con dos columnas, Expression y Value."
S3. Approved design verbatim: "**Cómo se usa:** Enter agrega la expresión, y elegís una fila y apretás **Delete** para borrarla."
S4. Approved design verbatim: "**Cuándo se evalúa:** en cada pausa, y también cuando elegís otro frame del stack (se evalúa en ese frame). Sin la sesión pausada, la columna Value muestra `—`. Si una expresión falla, muestra el error en su fila, por ejemplo `⚠ name 'count' is not defined`, y las demás siguen funcionando."
S5. Approved design verbatim: "**Persistencia:** por proyecto, en un archivo nuevo `projects/watches.json`. No toca `breakpoints.json`, así que no hay riesgo de compatibilidad."
S6. Approved design verbatim: "**Lenguajes:** Python, Go y los dos attach usan el request DAP `evaluate`. Node usa `Debugger.evaluateOnCallFrame`."
S7. Approved design verbatim: "**Un aviso, igual que en VS Code:** una watch **ejecuta código en tu programa**. Una expresión como `items.pop()` lo modifica en cada pausa. No la voy a bloquear, pero lo dejo documentado."

## Tasks
T1 | S5 | done: WatchStore load()/save() for projects/watches.json, watch_expression() normalization (strip, blank/NUL/>1000 rejected), max 100 per root, invalid files kept and save refused; RED module missing -> GREEN 12 passed | route: inline | Risk: none (new file, new records) | commit: see PR 1
T2 | S4,S6 | done: evaluate(expression, frame_id): DAP evaluate context watch (Python, Go, attach), Delve detail surfaced; Node Debugger.evaluateOnCallFrame with exceptionDetails as DebugError; Node value formatting shared with variables via _display; RED AttributeError -> GREEN 8 passed (real debugpy, Delve, Node) | route: inline | Risk: none (new method; Node variables formatting unchanged) | commit: see PR 1
T3 | S2-S4 | todo: WATCH section in CodeDebug (Input + DataTable), add/remove, evaluation per pause and frame, `—` when not paused, per-row errors, persistence | route: inline | commit: -
T4 | S7 | todo: docs (code-projects, tui, README) and verification | route: inline | commit: -

## Log
L1. 2026-11-09 user: "sí, sigamos con watch expressions", then "si" approving the design quoted in S2-S7.
L2. Exploration: sessions expose stack/scopes/variables but no evaluate. CodeDebug renders variables as a Static (#code-variables) rebuilt in _frame for the selected frame on every pause and stack row selection; the inspection row is Horizontal(#code-inspection) with #code-stack and #code-variables. Each storage module inlines its own atomic write (temp file + fsync + os.replace); WatchStore follows that convention.
