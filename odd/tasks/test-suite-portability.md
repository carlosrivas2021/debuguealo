# Restore the test suite
Branch: `fix/test-suite-portability`; delivery: ask-on-risk; forecast: 250 authored lines.
Runner: `.venv/Scripts/python.exe -m pytest`; initial RED: 37 failed, 347 passed, 5 skipped.

## Specs
S1. "Resuelve los test"
S2. "Review the delivered subagent output and continue."

## Tasks
T1 | S1-S2 | delegated | done | Platform test fixes reviewed; focused GREEN: 46 passed, 1 skipped; commit `25496bc`.
T2 | S1-S2 | delegated | in_progress | Reconcile TUI tests with current UI contracts; 71 passed, 1 failed; demonstrated transcript-isolation production defect under correction; commit pending.
T3 | S1-S2 | delegated | done | Named pyte dimensions, host/container assertions reviewed; RED: 3 failed, 3 passed; GREEN: 6 passed; commit pending.
T4 | S1-S2 | inline | pending | Full suite, lint, functional verification and native risk assessment; commit pending.

## Log
L1. User request: "Resuelve los test"
L2. User continuation: "Review the delivered subagent output and continue."
L3. Initial full suite: 37 failed, 347 passed, 5 skipped in 198.93 seconds on Windows. Exploration separated platform fixture assumptions, stale TUI assertions, and reversed terminal dimensions. Preserve existing behavior rather than weakening assertions. Platform tests and TUI tests are independent work units; terminal geometry is a narrow parent-owned correction. No publishing authorized.
L4. Workers launched together for disjoint platform tests and TUI tests; terminal geometry delegated after runtime context-backstop notification. Parent owns integration and final checks.
L5. Reviewed platform and geometry diffs after workers completed. Platform: 46 passed, 1 POSIX-only skip; geometry: 6 passed. No production security or lifecycle changes. Baseline Ruff/format command failed with 23 files needing formatting; unrelated baseline cleanup remains out of scope.
L6. TUI worker preserved documented keyboard-first controls, separate console and terminal-pane contracts. Focused run: 71 passed, 1 failed. Remaining RED shows Orders transcript visible after Catalog selection. Follow-up authorized within S1 to clear only displayed transcript on identity mismatch, retaining original-profile buffer. Initial Ruff lint actually passed; only formatting check failed.
L7. T1 committed as 25496bc (23 authored changed lines). Native committed assessment unavailable: native rejected the untracked feature document despite committed-only scope; facade returned nativeRisk=unassessable, independentVerifier=false. No review approval claimed; no retry of that assessment.
