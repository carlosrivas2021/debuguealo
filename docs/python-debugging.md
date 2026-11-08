# Python debug backend (T4a)

`PythonDebugSession` is an asynchronous, single-profile backend for the next Code TUI
integration. It does not wire Shift+F5, alter F5, edit profiles, or persist breakpoints.
Backend tests pass on Windows with debugpy 1.8.22, including real script/module debugging
and owned-descendant cleanup. TUI integration remains T4b work.

This page covers locally launched targets. To debug a process that is already running, such as
one in a container, see [Python attach](code-projects.md#attach-to-an-existing-pythondebugpy-target).

## Quick path for the TUI owner

```python
from debugealo.debugger import DebugError, PythonDebugSession

session = PythonDebugSession(
    on_event=handle_debug_event,             # synchronous, nonblocking, must not raise
    on_output=lambda category, text: append_output(category, text),
)
try:
    await session.start(selected_profile, {source_path: {5, 12}})
except DebugError as error:
    show_error(str(error))                   # never fall back to F5/run
# At a stopped event:
frames = await session.stack()
scopes = await session.scopes(frames[0]["id"])
values = await session.variables(scopes[0]["variablesReference"])
await session.step_over()                    # also step_in(), step_out()
# Wait for another stopped event before inspecting again.
await session.continue_execution()
await session.close()                       # Stop/shutdown; safe to repeat
```

Await `start` in an owned task so Stop can run while startup is pending. Cancelling that
task cleans up the owned adapter. `close()` also cancels an in-progress start. Each session
object accepts only one active start; Stop first before reusing it. The immutable `profile`
snapshot is retained after Stop for attribution; do not substitute the currently selected
profile when handling late output. Use a new session object for each TUI run if possible.

## Accepted commands

| Profile command argv | Interpretation |
| --- | --- |
| `["python", "main.py", "literal argument"]` | Script relative to the profile root |
| `["python3", "-u", "-m", "package.module", "arg"]` | Module, with unbuffered Python output |
| `["C:/project/.venv/Scripts/python.exe", "main.py"]` | Explicit selected interpreter |
| `["/project/.venv/bin/python", "main.py"]` | Explicit POSIX selected interpreter |

Versioned Python executable names are accepted. Other interpreter flags, `-c`, shell
commands, stdin programs, packages-as-script directories, npm and Go are rejected with
a supported-command explanation. Target arguments are literal argv, never shell text.
The original `CodeProject.command` is not rewritten; F5 still uses it unmodified.
Debug mode deliberately uses internal-console output (no interactive stdin API).

debugealo bundles `debugpy` and runs the debug adapter on its own interpreter; debugpy's
launcher then runs the target with the interpreter selected by the profile. That
interpreter does not need debugpy installed, but it must be a Python version debugpy
supports. The backend never installs anything into the target environment. A startup
failure or timeout produces an explicit error naming the interpreter, not a normal run.
DAP `telemetry` output is dropped and never shown as program output.

## Session contract

| API/state | Contract |
| --- | --- |
| `start(profile, {path: iterable_of_lines})` | Snapshot root/argv; configure initial breakpoints before execution; await configuration completion, not first pause |
| `set_breakpoints(path, lines)` | Replace the entire file's breakpoints; empty iterable removes them; return adapter breakpoint objects |
| `requested_breakpoints` | Requested 1-based lines, keyed by absolute source path; retained for intent, including after Stop |
| `verified_breakpoints` | Separate adapter responses (including relocated/unverified lines); cleared at shutdown |
| `stack()` | Up to 100 frames for the last stopped thread |
| `scopes(frame_id)`, `variables(reference)` | DAP scope/variable dictionaries; variables request asks for at most 200 entries |
| `continue_execution()`, `step_over/in/out()` | Valid only while stopped; invalidate current thread before resuming |
| `close()` | Idempotent owned-process teardown; clear thread and verified state |
| `state` | `idle`, `starting`, `running`, `stopped`, `closing`, `closed` |
| `exit_code` | Target DAP exit status, or `None` if unavailable/stopped; retained after close |

All inspection references become stale when execution resumes. Do not cache frames or
variable references across pauses. Breakpoint line values must be positive integers, never
zero-based values or booleans. Debug mode does not change source files or validate that a
returned source path is safe to display: the TUI **must reuse source_browser containment,
link, size and read-only safeguards**, even for adapter stack frames.

### Events and output

`on_event(message)` receives raw DAP events plus `state`, `adapterStarted`, `adapterExited`,
`transportClosed`, and `breakpoints` notifications. Alternatively consume `session.events`,
an asyncio queue for this run (replaced on start); attach to it after start begins. Drain
it continuously to avoid retaining an unbounded event history. `on_output(category, text)`
receives DAP output, with stdout/stderr separate from console/telemetry. Adapter PTY
startup diagnostics are kept as a bounded tail for errors, not mixed with target stdout.
Events such as `stopped` can arrive before `start` returns. A `continued` event clears the
current thread; `exited` records exit status; `terminated` and transport loss schedule
cleanup. The TUI should clear its own stack/variable/source-location presentation on
running/closing/closed and reject actions not appropriate for the current state.

## Ownership and transport boundary

- `command_argv` resolves the interpreter. `CodeSession.open_command` starts debugpy's
  adapter inside the existing owned `_code_worker`; target/launcher descendants inherit
  its Windows Job or POSIX process group. Shutdown reuses `CodeSession.close_session`.
- DAP travels over a separate IPv4 **127.0.0.1-only** TCP connection, never through the PTY.
  The adapter receives the same loopback bind address. No authentication/security flags
  are disabled. As with other local debugger ports, this is not isolation from other
  processes running as the same local user; ephemeral-port reservation/rebind has a
  small race and failure is surfaced rather than exposing a public listener.
- `subProcess` is false. Children are contained for cleanup but are not debug sessions.
  Reverse requests (including `runInTerminal`) are explicitly rejected, not executed.
- Startup and requests have bounded waits (`timeout=15` seconds by default); DAP frames
  are limited to 8 MiB. Stop closes transport and tears down the owned tree, rather than
  trusting a cooperative disconnect to terminate descendants.

## Verification and remaining work

The focused suite passed **17 tests, zero skipped**, on Windows with debugpy **1.8.22**:

```text
.venv/Scripts/python.exe -m pytest -q tests/unit/test_python_debug*.py tests/unit/test_dap*.py
17 passed in 15.67s
```

Both real script and module forms stopped at the requested 1-based breakpoint, returned
stack/scopes and local `answer = 41`, stepped in/over/out, and continued to stdout exactly
`RESULT:42\n`, empty stderr and exit code 0. The real descendant test passed: repeated Stop
removed the owned child before it could write its delayed survival marker. The same run
passed rejected-command, missing-adapter, startup-cancellation and DAP framing/disconnect/
timeout tests. No integration test silently skips a missing debugpy install.

The initial run before the authorized project-local adapter installation had 14 passes
and three missing-debugpy failures; that evidence was not waived. After the parent installed
debugpy 1.8.22, the recheck above passed without a backend correction. Shared terminal code
was unchanged; its prior CodeSession regression run passed all 10 tests. POSIX runtime,
TUI behavior and the full application suite were not exercised by this backend unit.

The implementation environment did not expose Context7 discovery or web tools, so current
official debugpy/DAP documentation could not be consulted. Reference endpoints for the
next verification owner are [debugpy launch settings](https://github.com/microsoft/debugpy/wiki/Debug-configuration-settings),
[debugpy adapter usage](https://github.com/microsoft/debugpy), and the
[DAP specification](https://microsoft.github.io/debug-adapter-protocol/specification).
These links are references, not a claim that they were fetched during implementation.
T4b owns bindings, visual controls, active-profile UI attribution and safe navigation.
