# Inspect local Docker containers and logs

DebugPilot only reads the configured local Engine. It does not start, stop, execute commands
inside, or remove containers. Compose is discovered from labels, without invoking Compose.

## Quick path

```console
uv run debugpilot doctor
uv run debugpilot containers
uv run debugpilot containers --json
uv run debugpilot logs payments-api --tail 100
uv run debugpilot logs payments-api --follow
```

`containers` includes stopped containers. `--json` exposes ID, name, image, state, UTC creation
date, ports, labels and optional Compose project/service. It emits unwrapped machine-readable JSON.
`logs` defaults to 100 historical lines. `--tail` accepts 0–10000; use `--tail 0 --follow`
for new logs only. Ctrl+C cancels following and closes/reaps the SDK worker, leaving the
container unchanged. Each command supports `--config` for the TOML file described in
[configuration](configuration.md).

## Log behavior and bounds

| Concern | Behavior |
| --- | --- |
| Channels | Docker multiplex framing preserves stdout/stderr. TTY output is marked `combined`; the channels cannot be recovered. |
| Timestamp | Original Docker RFC3339 timestamp, including nanosecond text, is retained. |
| Inferred severity | Critical/fatal, error/exception/traceback, warning/warn, info, debug; otherwise unknown. This is a heuristic, not structured-log parsing. |
| Ordering | Records follow Docker's stream order. stdout/stderr may interleave; no global timestamp ordering is promised. |
| Memory | 16 KiB per physical log line (oversize lines are truncated once), 1 MiB maximum multiplex frame, 256 KiB IPC record, 8 MiB metadata response, 10000 containers. |
| UI buffer | `LogBuffer` defaults to 2000 entries and 2 MiB payload bytes. The entry limit also bounds Python-object overhead. The CLI prints progressively rather than accumulating history. |
| Backpressure | A 128-entry engine queue blocks its producer. Normal EOF does not discard buffered history. Explicit shutdown may discard one queued entry to signal cancellation. |
| Stopped container | Historical logs can be read if the driver retains them; following ends once Docker reports the container stopped. |
| State changes | `DockerService.watch_containers()` polls and yields changed inventories; the upcoming TUI will consume this API. |

On a transient failure, follow retries at most three times, waiting 0.5, 1 and 2 seconds.
It requests an inclusive timestamp overlap (the newest observed second plus the preceding
second), and counts already-seen identical entries so legitimate repeated messages survive.
The replay window holds at most 2000 records. If timestamps are missing, skew exceeds the
window, or that bound is exceeded, a later reconnect fails explicitly and asks you to restart
the view rather than silently duplicate output. This is not durable/exactly-once log delivery:
daemon restarts, rotation and logging drivers can lose retained data outside the tool's control.

## Troubleshooting and verification

Not every logging driver supports reading logs. Unsupported-driver, missing-container,
permission and connection errors are reported without raw SDK exception contents. History
is streamed; tail is a line request to Docker, not a promise that unsupported drivers retain it.

The SDK runs in a private process with an empty Docker config and no inherited remote
context, proxy, or SSH variables. Cancellation kills and reaps that process. Read-only SDK
transport helpers are used to bound bodies and preserve frame stream IDs; compatibility is
covered for the installed Docker SDK 7.x by unit and real Engine tests.

```console
uv run pytest tests/unit/test_docker_service.py
uv run pytest tests/integration/test_docker_live_logs.py -v
```

Integration tests need a local daemon. They read existing retained logs and create one
test-owned fixture with no network, no mounts, read-only root, dropped capabilities and a
32 MiB limit. Only already-cached supported images are used; tests never pull. The fixture
is removed on teardown; no existing user containers are modified. Without Docker or a
cached fixture image the relevant test is skipped, not claimed as verified.
