# Debug Go projects with Shift+F5

Go debugging uses Delve's DAP adapter. Start the application normally with
`uv run debugpilot`; no `PATH`, `PYTHONPATH`, or `GOFLAGS` override is required. The
project virtual environment must be able to find the already-installed `dlv`. When Delve
is already present at `.tools/bin/dlv`, expose it to `uv run` by creating this project-local
link from the repository root (only when the destination does not already exist):

```sh
test -x .tools/bin/dlv && test ! -e .venv/bin/dlv && ln -s ../../.tools/bin/dlv .venv/bin/dlv
```

The link points to the existing tool; it installs nothing and changes no global settings.
Recreate it with the same command if the project virtual environment is replaced. Confirm
the application entrypoint with `uv run debugpilot version`. If Delve is missing or startup
fails, Code reports an actionable warning and never falls back to a normal run.

```python
from debugpilot.debugger import DebugError, GoDebugSession

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

Go support does not include attach, tests, binary targets, persistent breakpoints,
expression evaluation, source maps or interactive debug stdin.
