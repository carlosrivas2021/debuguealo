# Code tab IDE-style UX
Objective: make the Code tab feel like an IDE: yellow paused line, IDE layout, footer shortcuts, clearer texts.
Branch: feat/code-ide-layout; base: 9071968. Delivery: ask-on-risk (forecast ~350 authored lines). Runner: uv run pytest.

## Specs
S1. "cuando se detiene solo sale una flechita seria mejor que se sombreara la linea en amarillo" — the paused execution line gets a yellow background across the code area (arrow kept), cleared when execution clears.
S2. User selected "Estilo IDE (Recommended)": "Sidebar izquierda con perfiles + árbol; código grande al centro; panel debug a la derecha solo al pausar; terminal abajo colapsable; footer con atajos según contexto en lugar del párrafo de ayuda." Preview:
```
┌ Run ▶  Debug 🐞  Stop ■ ─ Ready: api ──────────┐
│PROFILES   │ main.py              │ VARIABLES   │
│> api      │  3  x = 1            │ x = 1       │
│  worker   │▶ 4  y = f(x) ░░░░░░░ │ CALL STACK  │
│───────────│  5  print(y)         │ f  main:4   │
│FILES      │                      │ (solo al    │
│ main.py   │                      │  pausar)    │
│ util.py   ├──────────────────────┴─────────────┤
│           │ TERMINAL (Ctrl+J colapsa)          │
└───────────┴────────────────────────────────────┘
 F5 Run  ⇧F5 Debug  F9 BP  F10 Over  F11 In  Esc
```
S3. "Todo me molesta" (answer to layout/flow/texts question) — texts that read like errors ("pending (no debugger)") and shortcut noise in labels are replaced by clear wording; shortcuts live in the footer.

## Tasks
T1 | S1 | inline | done: RED test_paused_execution_line_is_shaded_yellow_until_cleared failed, GREEN after post-style overlay; unit suite 694 passed | commit: pending (shares file with T2)
T2 | S2, S3 | inline | done (suite pending): RED 3/3 test_code_ide_layout.py on base copy, GREEN 3/3; SourceBrowser slots (sidebar header, editor side, bottom), toolbar + status row, Ctrl+J terminal collapse, footer bindings for F9/F10/F11/Shift+F11 in Code only, remove help paragraph, clearer texts | commit: pending

## Log
L1 (2026-11-08) "Quiero mejorar el ux de la parte de code" → "Todo me molesta, ademas cuando se detiene solo sale una flechita seria mejor que se sombreara la linea en amarillo"
L2 Strip.apply_style puts the style under segment styles, so TextArea's cursor-line bg won; Segment.apply_style(post_style=...) fixes it.
L3 Design: tests rely on browser.query_one(Tree/TextArea), so tree/editor stay inside SourceBrowser; profiles/debug/terminal are injected as slots to keep DOM compatibility.
L4 SourceBrowser got DEFAULT_CSS for its structural layout: standalone tests mount it without styles.tcss and the breakpoint button fell off-screen.
L5 F9 footer entry comes from a CodeWorkspace-level binding so containers keep the existing "Debugger controls are available in the Code area." notice (test_code_debug_f9).
L6 (2026-11-08) User: "Despues de que preciono f5 no se donde esta el focus, eso quiere decir que con las flechas no me puedo mover entre perfiles" → selected "Quedarse en perfiles (Recommended)". F5/Shift+F5 no longer focus the terminal; terminal title/border shows typing state; Escape now leaves an exited terminal too (TerminalPane.on_key). RED→GREEN test_f5_keeps_focus_on_profiles_and_terminal_shows_when_it_takes_keys.
L7 Suite (layout) 1 failed/696: test_run_and_debug_coexist... — hidden terminal resized to fallback 24 rows then shrank; pyte deletes top lines on shrink, wiping output. Fix: skip resize while size.height == 0. 20/20 GREEN.
L8 (2026-11-08) User: "Con shift f5 el stdout deberia salir abajo igual que con f5, no debajo de las variables". Debug output RichLog owned by CodeDebug, placed in #code-bottom with the run terminal; visibility follows the panel; Ctrl+J collapses #code-bottom. RED→GREEN test_debug_output_sits_at_the_bottom_like_the_run_terminal. Horizontal scrollbars hidden on narrow tables.
L9 (2026-11-08) User asked "Como se veria eso con 20 proyectos?" — measured 209x50: 11/20 profile rows visible (scrolls), tree keeps 30 rows. Leftover old hint at source_browser.py _populate replaced by SOURCE_HINT.
L10 (2026-11-08) User: "Sí, dale, y arreglá también lo del 3". Sidebar lists names only; folder + argv in #code-profile-details (test_code_projects updated to the requested behavior). Bug 3: selection applies exactly one bottom view (live wins; else last view chosen per profile via F5/Shift+F5/Reconnect). RED→GREEN test_a_profile_shows_one_bottom_view_when_it_has_a_finished_run_and_debug; 63 Code tests pass.
L11 (2026-11-08) User screenshot after L10: status said "Exited: 0" while Debug output was shown; empty Debug panel stayed after the session ended; profile highlight only covered the name. Fix: status follows the shown view; side panel only for live debug (finished keeps only its bottom output); Profile column width 26. RED→GREEN test_finished_debug_view_keeps_output_hides_panel_and_reports_debug_state; 60 Code tests pass.
L12 (2026-11-08) User screenshots: paused view OK; after Continue ended the program the empty Debug panel stayed. Fix: _debug_finished re-applies the view and status. RED→GREEN test_debug_panel_closes_when_the_selected_session_ends_on_its_own; 69 Code/debug tests pass.
