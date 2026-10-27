# DebugPilot configuration and lifecycle core

Install with `uv sync`. The headless library provides strict TOML settings, bounded events and owned-task cleanup. CLI and Docker workers are not included yet; dependency locking follows in its own unit.

Run `uv run pytest`. Core usage: import `Settings` from `debugpilot.storage.config` and `DebugPilotEngine` from `debugpilot.core.engine`; enter the engine with `async with`.
