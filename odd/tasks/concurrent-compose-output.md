# Concurrent Compose runs with per-project output

Objective: allow several Recreate / Build+Recreate runs at once (different projects) and keep each project's Compose output in its own bounded buffer.
Branch: feat/concurrent-compose, stacked on feat/containers-ui-redesign (PR #13). Delivery: separate PR on top of #13. Test runner: `uv run pytest -q tests/unit` with `HOME` pointed at a scratch dir.

## Specs

- S1 — Per-project output. "hacé el buffer por proyecto". Compose output lines are stored per Compose project (the run's `plan.project.project_name`). Selecting a project row, a launch profile row, or any container row of that project shows that project's buffer in the Output card. A run never writes into another project's buffer; a new run of project A clears only A's buffer.
- S2 — Concurrency. "permití varios a la vez". Recreate / Build+Recreate (launch profile actions and the Compose dialog path) may run concurrently for different projects. A second run of the *same* project while one is running is rejected with a warning. Matches the user's rule for stops: "no puedas mandar a hacer algo al contenedor que mandaste a detener por ejemplo pero los otros deberia poder dejarte" — only the busy project/containers are blocked.
- S3 — Confirmation bar is freed on confirm. After confirming a Compose run, the inline confirmation bar is dismissed immediately (as stops already do) so another action can be previewed/confirmed while the run continues. Progress and results go to the project's output buffer and toasts.
- S4 — Mid-run prompts do not collide. The missing-image download consent that a run may request uses the inline bar; if the bar is busy (another confirmation/consent pending) the request waits for it instead of overwriting it. Each consent stays bound to its own run's plan/profile (existing `_retry_profile_is_current` safety stays per run, not via global `_pending_profile`).
- S5 — Cancelling. Esc (cancel_compose) with no pending bar decision cancels the running Compose run of the *selected* project only (previous behaviour cancelled the single global run). Other projects' runs keep going.
- S6 — Memory bound. "no quiero que esa memoria suba demasiado, crea un limite o ttl para que desaparezca lo mas viejo". Keep at most a fixed number of project buffers (LRU eviction of the least recently written/viewed project; assumption: 8) and keep the existing per-buffer caps (1000 entries / 1 MiB). Projects with a running Compose run are never evicted.
- S7 — Unchanged: stop output (`[Stop] …`) stays global as today; credential refresh / credential batch recreate stay exclusive (one at a time, blocked while any Compose run is active, and vice versa); stops remain blocked only for projects being recreated (existing `_project_is_stopping` rule mirrored: a project with a running Compose run cannot be stopped from its rows — assumption, consistent with S2).

## Tasks

- T1 — S1–S7 — delegated (context backstop: parent session context is very large) — done, verified (no blockers), full suite 705 passed; RED/GREEN: tests/unit/test_tui_concurrent_compose.py 6 app tests RED on base behaviour, 7/7 GREEN

## Log

- L1 (2026-11-09, user): "dale, hacé el buffer por proyecto y permití varios a la vez"
- L2 (2026-11-09, user): "dale, seguí, pero no quiero que esa memoria suba demasiado, crea un limite o ttl para que desaparezca lo mas viejo"
- L3 (2026-11-08, user, context for S2): "Entiendo que no puedas mandar a hacer algo al contenedor que mandaste a detener por ejemplo pero los otros deberia poder dejarte"
- L4: Route: T1 delegated to one bounded writer (context backstop). Risk item 4 (concurrency/async ordering) → independent verifier after T1.
- L5 (T1 writer): Per-project `ProjectOutputBuffers` (LRU 8, 1000 entries / 1 MiB each, running projects never evicted) in `tui/compose_output.py`; per-run `_ComposeRun` in `app.py`; `_compose_tasks` per project, `_credential_task` exclusive. Resolved ambiguities: (a) `_retry_profile_is_current` now checks only the run's own profile/key against launch.json (the old selection/revision condition was dropped, otherwise a consent could never wait for a bar busy with another project's preview, making S4 unreachable); (b) a new Compose run no longer clears the global `[Stop]` output (S1: a run clears only its project's buffer); (c) after a consent is answered the bar is dismissed and the retry reports to the project's output; (d) the credential batch keeps the bar as its progress line and is not registered per project.
- L6 (2026-11-09): Independent verifier: no blockers, S1–S7 PASS. Parent fixed advisories A2 (a consent's cleanup no longer drops a preview opened right after the answer; verifier race probe now keeps the preview), A3 (`_open_compose` refuses a busy project before discarding another pending preview) and A4 (consent names the launch profile and project). A1 kept as implemented: a Compose run no longer clears the global `[Stop]` lines (reported to the user). A5/A6 left as advisories.
