# Compose failure output and missing-image consent
Objective: expose real Compose errors and require explicit in-TUI approval before downloading missing images and retrying the same profile.
Branch: codex/launch-owned-sidebar; delivery: ask-on-risk, no push; forecast: 300–400 authored lines; runner: /tmp/debugealo-launch-grouping/venv/bin/python.

## Specs

### S1 — Show actual failure output
> Si, deberia mostrar el error real

> Los logs de por ejemplo descargar la imagen o reiniciar podrian salir en los logs del medio

Show Compose execution output (success, failure and download/recreate progress) in the existing central log viewer, distinguished from container logs by a Compose/profile prefix. Stream output while the operation is running and keep the latest operation output available after completion. Do not replace the dashboard with a modal or introduce tabs. Keep missing-image consent in the existing inline action bar, with Cancel as the safe default. Render external output literally and retain it only in bounded memory, not a new log/config file. Preserve selected-profile/child ownership through refresh, success and cancellation; switching projects must not display an unrelated operation's output. Empty output still shows an actionable exit summary. Internal resolved config/environment probes must never be streamed to the viewer.

### S2 — Ask before downloading missing images
> Si no tiene la imagen deberia preguntarte quieres descargarla

A concrete missing-image failure offers explicit Download and retry versus Cancel in the TUI. Only affirmative user action may permit downloading missing images and retrying that same pinned project/scope; no automatic pull, blanket always-pull policy or retry on arbitrary failures. Cancellation performs no additional operation. Reject stale file/environment/profile targets before download/retry. Preserve normal --pull never behavior when no download consent exists, ensure no overlapping/duplicate operations and show retry failures rather than looping automatically. No real downloads or container mutation in tests.

### S3 — Stop from the saved profile parent
> C:\Users\Usuario\Pictures\Screenshots\Captura de pantalla 2026-10-30 180448.png No me deja hacer stop, y no veo los logs

The screenshot selects the Agente saved-profile parent with one active child. Stop from that selected parent must offer confirmation for its active matching project containers, never unrelated projects or inactive siblings; Cancel does nothing and Confirm executes exactly the pinned active IDs once. Child Stop remains container-scoped. Existing 1–32 target bound and operation overlap protection stay intact. The actual example runs sleep infinity and emits no container stdout/stderr; do not fabricate log lines or change external example behavior. Execution-output location is resolved in L7: use the existing central log viewer.

### S4 — Stopped profile state
> No deja hacer stop a todo el proyecto, ademas deberia no decir ready como estado sino Stop

A valid saved profile without active matching containers displays the exact status Stop instead of Ready. Preserve Pending for invalid/incomplete profiles and existing active-state reporting. Project-parent Stop behavior is S3 and must not require selecting individual children.

## Tasks

- T1 | S1 | delegated same bounded worker: original modal output surface | dropped | commit: none | Superseded by user L7; T5 implements central execution logs and inline consent while retaining literal-output checks.
- T2 | S2 | delegated same bounded worker: confirmation-gated missing-image retry plus regression tests/docs | done | commit: 1d374d5 | Effective-config snapshot implemented and 56 focused passed / 1 deselected; complete proof blocked by T7 and pending independent T3. Risk: items 2/4.
- T3 | S1–S4 | parent assessment, independent verification and local work-unit commit | superseded | commit: 1d374d5 | Delivered without a separate independent T3 run; current unit suite is the available proof. Must verify current central-output architecture, full runtime-input coverage, parent Stop and exact Stop status before commits. Prior modal approval is not current S1 proof. No push or live Docker operations.
- T4 | S3 | delegated same worker after security correction: saved-parent Stop regression/fix | done | commit: 1d374d5 | Parent guard RED reproduced; 7 Stop tests passed, child/unowned behavior preserved; independent T3 pending.
- T5 | S1–S2 | delegated same worker after T2/T4: central live execution output and inline download confirmation | done | commit: 1d374d5 | 17 streaming/guard/central/Stop checks passed, aggregate 88 passed; central architecture implemented, independent T3 pending.
- T6 | S4 | delegated same worker with central-output integration: stopped profile label | done | commit: 1d374d5 | Exact Stop implemented; active/inactive/Pending status GREEN passed, no separate RED captured.
- T7 | S1–S4 | bounded additional correction for three unresolved suite failures | closed | commit: none | No longer reproduces (see L-final). Requires explicit user authorization for a further correction batch after the stated final runtime-guard budget; do not rerun or edit automatically.

## Log

### L1 — Original requests
User: "Si, deberia mostrar el error real"
User: "Si no tiene la imagen deberia preguntarte quieres descargarla"

### L2 — Evidence and scope
Baseline HEAD 320e18b (previous feature code 994964c). User screenshot shows Compose exited 1 for valid Agente profile; subsequent docker image inspect screenshot confirms alpine:3.22 missing. Current ComposeResult includes retained merged stdout/stderr but inline app ignores output. ComposePlan always uses --pull never; legacy ComposeDialog already displays literal Text(result.output). Existing worktree tracked differences are CRLF-only; preserve unrelated local state and .debugpilot/. This change does not globally replace pull policy or execute actual Docker. Missing-image classification must be narrow and deterministic: do not turn permission, registry, network or generic not-found errors into download requests. Preserve config/environment fingerprints and existing pre-confirmation launch-profile pinning. Known baseline suite failure: tests/unit/test_compose.py::test_cancellation_during_launch_drains_a_real_childs_full_stdout, independently reproduced before this feature. No other failing check is pre-authorized as baseline.

### L3 — Initial implementation and compatibility adaptation
Worker mvvfcs01-b-6rxt implemented failure output and consent-gated single retry. RED: 5 focused failures; GREEN: 73 passed / 1 known-baseline deselected. Full suite: 257 passed / 2 failed / 3 deselected; one named baseline Compose cancellation, one old failure-path log test that does not close the newly required modal. Parent approved the narrow additional surface tests/unit/test_tui_restart_logs.py for adapting that interaction, retaining all stream/selection assertions. Continuation mvvg29uy-c-w1on running; no human decision required. Native assessment unassessable due ambient undeclared untracked files; agent escalation item 2 requires independent verification.

### L4 — Corrected self-verification and independent handoff
Only the non-cancellation branch of the old log-preservation test now closes the required modal; all original assertions retained. Exact regression RED 1 failed / 1 passed, GREEN 2 passed. Focused 82 passed / 1 known-baseline deselected. Full nonintegration suite 258 passed / 1 named baseline failure / 3 deselected. Ruff check passed and format 7 files clean. Parent spot-check of output/consent-cancel/generic/retry cases: 5 passed in 9.10s. Independent verifier mvvgd7wi-d-e77u inspecting S1–S2 in isolated state. Estimated authored diff about 450 lines; keep coherent code/test/docs work-unit boundaries rather than shrinking tests. Native assessment still unavailable due ambient untracked selection; no review approval claimed.

### L5 — Independent findings and pending UX decision
Verifier reported S1 met, S2 one blocker with two inputs: editing implicit .env without explicit --env-file or YAML service env_file while consent waits still permits the new --pull missing retry. Ordinary-run pinning absence predates this change, but authorizing the new retry with stale runtime environment violates S2. Other scoped recheck cases: 13 passed; only the two runtime inputs failed. Initial scratch harness assumptions (double Enter, create-only save API, explicit-env .env case) were corrected separately. Correction mvvgoabg-e-wist is limited to effective runtime environment snapshot/revalidation, no whole-workspace hashing or live Docker.
User: "C:\\Users\\Usuario\\Pictures\\Screenshots\\Captura de pantalla 2026-10-30 180311.png Funciono pero porque manda a otra pantalla ademas deberia mostrarse en algun lado el log de la ejecucion"
Parent proposed dashboard tabs for container logs/execution output plus inline confirmation; awaiting user confirmation before that visual rewrite. Security correction is independent and continues without changing the modal meanwhile.

### L6 — Stop report and silent example
User: "C:\\Users\\Usuario\\Pictures\\Screenshots\\Captura de pantalla 2026-10-30 180448.png No me deja hacer stop, y no veo los logs"
Parent direct reads: app.action_stop_selected explicitly rejects a selected saved profile parent; child Stop and _group_members already exist. External user-selected example local/agente/docker-compose.yaml extends local/docker-compose.base.yaml, whose command is [sleep, infinity] and therefore produces no container stdout/stderr by itself. No live logs/Stop invoked. S3 is a narrow authorized compatibility correction; do not modify external fixture or invent log output.

### L7 — User resolves execution-output location
User: "Los logs de por ejemplo descargar la imagen o reiniciar podrian salir en los logs del medio"
Confirmed implementation direction is the existing central log viewer, not tabs or a separate modal. Distinguish Compose output with a profile prefix; retain bounded latest-operation output through same-project selection/refresh and show progress as produced. Missing-image consent remains inline with safe default Cancel. The snapshot security correction and Stop fix finish first; T5 then replaces superseded modal UI and tests, keeping permission/environment assertions. No change to plain-restart semantics or real Docker authorization.

### L8 — Parent Stop reiterated and state label
User: "No deja hacer stop a todo el proyecto, ademas deberia no decir ready como estado sino Stop"
S3 remains project-level Stop with active-only confirmation; S4 adds exact Stop status for a valid inactive profile. Do not rename Pending or invent a plain-restart action. No live project Stop authorized for the agent; verification uses mocked Docker.

### L9 — Security/Stop correction evidence and central-output handoff
Worker mvvgoabg-e-wist completed scoped S2/T4: original dotenv/env_file verifier probes RED reproduced then 2 passed; new public retry-environment tests initially 4 failed before API then GREEN. Focused 54 passed; parent Stop parameterized RED then 7 Stop tests passed. Ruff lint/format 7 files clean. No additional full suite for superseded modal architecture. Worker captures bounded literal runtime inputs without extra Compose commands and rejects stale fingerprints. Parent noted the real example uses external-file extends; current source scans only top-level project files, so inherited env inputs may be omitted. This concern was sent to the same worker for fail-closed verification, not claimed fixed. Continuation mvvhbp7o-f-pq3d implements T5/T6, preserving S2/T4. No live Docker or actual external-project edits.

### L10 — Plan audit and current proof boundaries
User: "Quiero que actualices y mantengas al día el plan de trabajo de la funcionalidad en curso. Ya mostraste el estado de las tareas: la protección contra cambios de `.env/env_file` y el Stop desde el perfil del proyecto figuran como hechos; los logs de ejecución en vivo de Compose en el panel central están en curso; el cambio de estado de `Ready` a `Stop` está pendiente; y la verificación final de permisos, Stop, logs y estado, junto con la preparación de commits locales sin push, sigue pendiente.\n\nRevisá el plan actual, actualizá cualquier progreso real desde ese último estado y continuá con el trabajo pendiente. No marques como completada una tarea si todavía falta implementación o verificación. Conservá como terminados solo los pasos ya implementados y comprobados; si falta algún paso para cerrar la funcionalidad, agregalo al plan y seguí adelante."
Audit: T2 reopened pending because literal direct env tests do not establish inherited extends coverage or final consent safety. T4 remains self-verified (7 tests), with independent parent/child scope checks still explicit in T3. T5 worker running, no final source/tests result delivered. T6 still pending; current app still displays Ready. T3 explicitly includes all S1–S4 and commit outcome; no source commit created for this feature. No new sweep or final-completion claim.

### L11 — Central-output implementation and inherited-input compatibility
Worker mvvhbp7o-f-pq3d delivered central live Unicode output, bounded same-profile/project retention, inline consent and exact inactive Stop. Specific 17 passed; focused 88 passed / 1 baseline deselected; full suite 270 passed / 1 named baseline cancellation failure / 3 deselected. One larger focused aggregate had the previously observed intermittent grouping-selection failure (105 passed / 1 failed / 1 deselected); later full suite passed that case. Ruff lint/format 9 files clean. S4 test GREEN only, no separate RED recorded. Inherited extends/include is denied consent rather than fingerprinted: safe but fails the user's original extends-based sample. Parent therefore requests last bounded S2 correction mvviva5b-g-2zri using a private read-only effective Compose configuration snapshot, supporting unchanged inherited inputs and rejecting changed ones. Config values must never stream or persist. Remove production mock-identity detection for output callbacks; use the real optional signature and faithful test doubles. No ordinary-run behavior changes, real Docker or commits. Independent T3 verification remains pending for the final source candidate.

### L12 — Final bounded runtime correction returns partial
Worker mvviva5b-g-2zri implemented async private compose config --format json snapshot: unchanged synthetic inherited env permits consent, changed inherited env rejects before mutation, config probe does not stream. Runtime guard focused 56 passed / 1 deselected; Ruff lint/format 9 files clean. Full nonintegration suite: 272 passed / 4 failed / 3 deselected. One known baseline Compose cancellation; two test_compose_launch.py pre-spawn assertions now misread fake_process's initialized calls dictionary; one unexplained test_tui_grouping.py selection/stream assertion, not accepted as baseline. Parent read both affected tests but performed no additional checks or edits. Final correction budget exhausted: T7 awaits an explicit new bounded authorization; independent T3 and all commits remain pending. Normalized tracked scope totals 1153 additions / 63 deletions plus 364 new test lines; obsolete unused untracked compose_output.py has 93 lines and is not a delivery artifact. Review workload exceeds initial forecast and must be resolved before any commit/delivery. No actual Docker/config access or feature commits.

### L-final — Status reconciliation (2026-11-10)

The feature shipped in 1d374d5 (feat: integrate compose overrides and dashboard terminal). The three T7 failures (baseline Compose cancellation, two test_compose_launch.py pre-spawn assertions, one test_tui_grouping.py selection assertion) no longer reproduce. 2026-11-10 status reconciliation: tests/unit with -m "not integration" on main 783a6b8: 864 passed, 1 deselected, 0 failed (1032s). Integration tests not run (need real Docker). No native review approval is claimed.
