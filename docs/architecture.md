# UI-independent local diagnostics

Core owns bounded events and task cleanup, with no Textual imports. The CLI injects DockerDiagnostics via a protocol. The SDK runs in a private short-lived process with empty Docker configuration, minimal environment and disabled environment/proxy discovery. Output is bounded; cancellation kills and reaps the worker. No telemetry or variable persistence is introduced.

The engine is single-loop and nonrestartable. Subscribers own pending reads; tasks must cooperate with cancellation. Future Textual or Qt adapters can own the loop and reuse the same engine. No TUI, DAP or Qt implementation exists in this unit.
