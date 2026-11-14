# Debug Go projects with Shift+F5

Go debugging uses Delve's DAP adapter. Start the application normally with
`uv run debugealo`; no `PATH`, `PYTHONPATH`, or `GOFLAGS` override is required. The
project virtual environment must be able to find the already-installed `dlv`. When Delve
is already present at `.tools/bin/dlv`, expose it to `uv run` by creating this project-local
link from the repository root (only when the destination does not already exist):

```sh
test -x .tools/bin/dlv && test ! -e .venv/bin/dlv && ln -s ../../.tools/bin/dlv .venv/bin/dlv
```

The link points to the existing tool; it installs nothing and changes no global settings.
Recreate it with the same command if the project virtual environment is replaced. Confirm
the application entrypoint with `uv run debugealo version`. If Delve is missing or startup
fails, Code reports an actionable warning and never falls back to a normal run.

```python
from debugealo.debugger import DebugError, GoDebugSession

session = GoDebugSession(on_event=handle_debug_event,
                         on_output=lambda category, text: append_output(category, text))
try:
    await session.start(selected_profile, {source_path: {9}})
except DebugError as error:
    show_error(str(error))
# At a stopped event: frames = await session.stack()
# scopes = await session.scopes(frames[0]['id'])
# values = await session.variables(scopes[0]['variablesReference'])
# await session.step_over()  # also step_in(), step_out()
# await session.continue_execution()
await session.close()  # Safe to repeat; cancels startup and removes owned processes.
```

Await `start` in an owned task so Stop can interrupt startup. One session supports one
active profile; use a new session per UI run. Callbacks are synchronous and must not block
or raise. `session.events` is replaced at each start; attach while startup is in progress
because events such as `stopped` may precede completion.

## Supported command grammar

| Original profile argv | Debug target |
| --- | --- |
| `go run main.go [args...]` | `main.go` in the profile root |
| `go run . [args...]` | The Go package in the profile root |

Target arguments are literal argv, not shell text. Unsupported forms (including `go test`,
flags, other source files, package patterns, and direct `dlv` commands) produce an
actionable `DebugError`. The original profile command tuple is retained unchanged, so the
regular F5 run command remains as configured. Go debug launch alone sets Delve's
`buildFlags` to `-buildvcs=false`, preventing a missing or unavailable Git repository from
blocking the debug build. This does not set `GOFLAGS`, alter the user's environment, or
change F5's existing run command. Delve must already be installed and available as `dlv`
on the application PATH; the backend does not install or update tools. Missing Delve has
an explicit error and does not launch Go in run mode.

Delve compiles the program before debugging starts, and the state shows `Debug building`
meanwhile. The build has no deadline, because a first build with an empty Go build cache or
a large project can take minutes without anything being wrong; press **Stop** to cancel it.
Connecting to Delve and configuring the session still use the startup timeout. A failed
build is reported at once as `Unable to build the Go program: ...`, and the compiler output
appears in the debug output.

## Code UI walkthrough

Create a dedicated sample in a trusted folder, for example `go-sample/main.go`:

```go
package main

import "fmt"

func main() {
	answer := 41
	answer++
	fmt.Printf("RESULT:%d\n", answer)
}
```

Register a Code profile in the separate central `projects/launch.json`:

```json
{
  "name": "Go sample",
  "workspaceFolder": "/absolute/path/to/go-sample",
  "command": ["go", "run", "main.go"]
}
```

Select the profile in Code and open `main.go`. Set a pending breakpoint on the
`answer++` line, immediately after `answer := 41`, then press **Shift+F5**. The breakpoint
stops before the selected line executes, so `answer` has already been initialized to `41`.
At the stop, inspect the stack and the `answer` variable (`41`), then choose **Continue**. The Go output should include
`RESULT:42`. **F5** runs the original `go run main.go` command without debugging. The
profile command tuple is not rewritten when debugging. This walkthrough does not require
or modify a project beyond the sample file and manually edited profile.

The Code UI keeps one live session per saved profile, not one global session: distinct
profiles can run, debug, or attach at the same time. Selecting another profile changes
which session's output and controls are shown; **Stop** or **Disconnect** acts only on that
selected session. Reloading edited or removed profiles does not retarget an active session;
its saved name and original launch settings remain pinned until it is stopped or disconnected.
Distinct Go attach endpoints may coexist, but the same host/port is rejected for another
profile because remote breakpoint cleanup is shared. Reconnecting after unexpected loss is
always an explicit action.

When an authoritative exit code is reported, the UI displays that code. Delve may close
without reporting one; the UI then displays the exact status **“finalizado; código de
salida no disponible”**. This indicates completion with unknown status, not success.

## Public session contract

The API follows `PythonDebugSession`: `start(profile, {path: iterable_of_lines})`,
`set_breakpoints(path, lines)`, `stack()`, `scopes(frame_id)`, `variables(reference)`,
`continue_execution()`, `step_over()`, `step_in()`, `step_out()`, and idempotent `close()`.
Requested 1-based breakpoint intent is kept separately from Delve's verified response;
verified entries and frame/thread references are cleared on close. Delve is configured to
send target stdout/stderr as DAP output events; the separate `output` launch option remains
the compiled binary path. Completion is signaled by `terminated`/transport closure. The
backend retains an authoritative DAP `exited.exitCode` when Delve supplies one; otherwise
`exit_code` remains `None`. The Code UI displays the reported code when present; otherwise it uses
**“finalizado; código de salida no disponible”** and never infers success from termination
or adapter exit. Close cancels pending startup and reuses `CodeSession` ownership/containment
to stop the adapter and all descendants.

Delve's DAP listener is bound explicitly to IPv4 loopback (`127.0.0.1`), with default
version checks/security behavior intact. As with other local adapters, this is not isolation
from other processes running as the same user. Delve build output is directed to an owned
system temporary directory and removed at session teardown, rather than being written into
the project source tree. Go's normal build cache may still be used by the Go toolchain.

## Attach to an existing headless Delve target

`GoAttachSession` connects directly to an existing Delve DAP endpoint. It does not start a
local adapter, build a program, or launch another copy of the target. The externally owned
process and its container lifecycle remain under Containers.

Register an attach profile in Code's `projects/launch.json`:

```json
{
  "name": "Go remote",
  "workspaceFolder": "/local/path/to/go-debug",
  "goAttach": {
    "host": "127.0.0.1",
    "port": 2345,
    "remoteRoot": "/app"
  }
}
```

`command` may be omitted for an attach-only profile (internally its argv is empty). If
present, the command remains the existing F5 run command; attach never executes it. The
`goAttach` object requires exactly these fields: `host` must be `127.0.0.1`, `port` an
integer from 1 through 65535 (booleans are not integers here), and `remoteRoot` an absolute
POSIX path with no backslashes or `..` segments. Invalid profiles are rejected without
rewriting the launch file. The backend connects only to the validated loopback endpoint.

```python
from debugealo.debugger import DebugError, GoAttachSession

session = GoAttachSession(on_event=handle_debug_event)
try:
    await session.start(selected_profile, {local_source_path: {9}})
except DebugError as error:
    show_error(str(error))
# At a stopped event, use stack(), scopes(frame_id), and variables(reference).
# Also available: set_breakpoints(), step_over(), step_in(), step_out(),
# and continue_execution().
await session.close()
```

The attach request uses DAP `mode: "remote"` and maps the local `workspaceFolder` to
`remoteRoot`. Breakpoints are sent using mapped remote paths; stack-frame sources are mapped
back to local workspace paths and checked for containment before Code opens them. The API
reuses the Python debugger's inspection and stepping methods. It supports breakpoints,
stack, scopes, variables, stepping, continue and watch expressions, but not interactive
debug stdin.

`close()` clears only this session's registered remote breakpoints, then resumes the target
if it is stopped before sending DAP `disconnect` with `terminateDebuggee: false`. Requested
local breakpoint intent is unchanged and is reapplied on reconnect. If the Go attach transport
is lost unexpectedly, Code reports **Unexpected disconnect; target state UNKNOWN** and offers
an explicit **Reconnect** action pinned to the same profile. Breakpoints remain requested but
return to pending until Delve confirms them after reconnection. There are no automatic retries,
target restarts, or local Python/Node recovery actions; the target's actual state must be checked
in Containers. Startup cancellation
before attach configuration completes avoids breakpoint-clear and resume commands. Neither
close nor cancellation sends `terminate`; the target process remains externally owned. If
clearing breakpoints or resuming fails because the transport is unavailable, cleanup still
finishes and emits a visible warning; the UI reports the target state as unknown rather
than claiming it resumed. Delve must already be running and reachable on the configured
endpoint. The backend does not start or stop Delve, manage the container, or modify the
target's source tree.

Go launch support does not include tests or binary targets. The program reads its standard
input from the **Program input** field; see [program input](code-projects.md#program-input). Watch expressions are evaluated by Delve with its own expression
syntax.
