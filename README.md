# DebugPilot local diagnostics

Install with `uv sync`; run `uv run debugpilot version`, `uv run debugpilot doctor` and `uv run pytest`. CLI defaults to help; no TUI is implemented yet.

Doctor uses a local-only isolated SDK worker with bounded output and cleanup. It exits0 for successful checks,1 for unavailable Docker and2 for invalid configuration. Container discovery/logs and debugging arrive later. Dependency locking is a subsequent reproducibility unit.
