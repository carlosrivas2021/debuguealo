# Container stats
Objective: show live CPU and memory for the selected container in its details card without streaming stats. Branches: feat/container-stats-{1-backend,2-ui}; base: current main.
Delivery: stacked-to-main (user's strategy from earlier features): PR1 worker + service + CPU math (T1-T2), PR2 details card polling + docs (T3-T4); runner: uv run pytest.

## Specs
S1. User concern verbatim: "Lo que me preocupa de los stats es que no es lo mismo que con los logs va a estar permanentemente llamando al stream?"
S2. Approved design verbatim ("si"): "**Stats solo del contenedor seleccionado,** mientras su card de detalles esté visible. Nada para el resto de la lista."
S3. Approved design verbatim: "**Polling de una muestra cada ~2 s** a través del **worker de inventario que ya está vivo.** No se abre ningún proceso ni conexión nueva, y es el mismo ritmo al que ya se refresca el inventario."
S4. Approved design verbatim: "**CPU % calculado entre dos muestras consecutivas.** `one_shot` no trae la muestra previa, así que la diferencia la calculo yo. La memoria sale directo de cada muestra."
S5. Approved design verbatim: "**Se corta solo** cuando cambiás la selección, cerrás la card o salís de la app."

## Tasks
T1 | S3,S4 | done: worker `stats` (stream=0, one-shot=1, bounded_json) accepted by serve; container_name() shared with logs; ContainerStats.from_docker (cgroup v1/v2, stopped -> None) and cpu_percent | route: inline | Risk: none | commit: see PR 1
T2 | S3 | done: _inventory_records(request) serves inventory and stats on one worker and lock; DockerService/engine/protocol container_stats(); RED ImportError/AttributeError -> GREEN unit 6 + real Docker 2 (busy container >10% CPU, stopped has no values); worker/service/integration tests pass except the stale logs test fixed by PR #25 | route: inline | Risk: none | commit: see PR 1
T3 | S2,S4,S5 | todo: details card CPU/memory rows; 2 s polling only for the selected, visible container; stops on selection change, hidden card, app exit | route: inline | commit: -
T4 | S1-S5 | todo: docs and verification | route: inline | commit: -

## Log
L1. 2026-11-09 user concern (S1), then "si" approving the design quoted in S2-S5.
L2. Exploration: DockerService._records spawns one Python worker subprocess per stream (logs, stop); inventory uses one persistent `--serve` worker answering one JSON request per line, ending with `done`, behind _inventory_lock. Docker SDK stats(stream=False, one_shot=True) returns one sample without waiting two cycles; one-shot needs API >= 1.41 (local daemon: 1.51). Stats are a 1/s stream by default, hence polling.
