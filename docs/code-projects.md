# Register, run and debug code projects centrally

Choose **Code**, then **Open code launch.json** (or Ctrl+O / Ctrl+N while in Code).
The terminal editor creates the file only when explicitly requested. Add your profiles,
save and exit; the table reloads. **Reload code profiles** picks up external edits.

The dedicated file is `projects/launch.json` beside debugealo's central container
`launch.json` and `config.toml`. It never uses the application working directory or
modifies container profiles, including when an explicit local Docker workspace is used.
The UI shows the full path. No configuration migration or automatic project scan occurs.

```json
{
  "version": 1,
  "configurations": [
    {
      "name": "API",
      "workspaceFolder": "C:/work/api",
      "command": ["python", "main.py"]
    },
    {
      "name": "Web",
      "workspaceFolder": "C:/work/web",
      "command": ["npm", "run", "dev"]
    }
  ]
}
```

Replace the example folders with existing absolute directories on your machine
(`/home/you/api` also works). Names must be nonempty and unique. Commands are argument
arrays, not shell strings; Go's example is `["go", "run", "main.go"]`.
Invalid configuration is reported in Code without disabling Containers or rewriting
files. Reading a missing file shows an empty list without creating anything.

Containers / Code switching preserves mounted views and does not start or stop
processes. Container action shortcuts are inactive in Code.

## Layout

Code is laid out like an IDE: profile names and the file tree on the left (the selected
profile's folder and command appear under the list), source in the center, the **Debug** panel (controls, stack, variables) on the right while a debug
session is selected, and the bottom area below: the Code terminal for runs or **Debug output**
for debug sessions. **Ctrl+J** hides or shows the bottom area. The footer lists the shortcuts
available in the current area. Selecting a profile shows one bottom view: its live session,
otherwise the run or debug view you used last for that profile.

**Ctrl+Left** and **Ctrl+Right** move focus between the panes in screen order: profiles,
file tree and source, wrapping around at either end; from a button they go to the
profiles. They skip the buttons, and in the source they replace the word jump of the
read-only view. In a text field or while typing into the terminal they keep their usual
word movement.

F5 and Shift+F5 never move focus, so the arrow keys keep moving between profiles. Click the
terminal to type into the program; its border turns yellow and reads
**typing — Esc to leave**. **Escape** returns to the profiles, even after the program exited.

## Run without debug

1. Select a profile in **Code** (left sidebar) and press **F5** or click **▶ Run**.
2. Click the Code terminal to type interactive input. **Escape** returns focus to profiles.
3. Click **Stop** to end that Code process tree. After stopping or exit, run again with F5.

Each saved profile can own at most one pending or active Code run. Different profiles
may run simultaneously and may run alongside local debug contexts. F5 on a profile that
already has a live run selects its terminal; it does not spawn a duplicate. F5 on that
profile's active debug context selects the debugger instead of changing modes, and continues
it when paused. Selecting
another profile never stops its background run; its terminal screen and output are retained.
**Stop** affects only the selected run or debug context. The status line reports the
selected context's `Starting`, `Running`, `Exited: <code>`, `Stopped`, or startup error.
A new run after exit starts with a fresh terminal screen. Quitting debugealo stops all
owned Code runs, including startup in progress.

Commands inherit the environment and run in their configured folder, using argv rather
than a host shell. On Windows, npm's standard `npm.cmd` entry is resolved to Node plus
`npm-cli.js`; other batch launchers require their underlying executable/script instead.
Missing executables and unavailable PTY support produce errors, not a shell fallback.
Windows uses an owned kill-on-close Job Object; POSIX uses an owned process group.
Remaining descendants are terminated on stop **and when the main command exits**.
Do not use this runner for detached background services intended to survive the profile.

## Browse source and mark pending breakpoints

1. Select a Code profile. Expand directories in the file tree, then select a file.
2. Move the cursor to a line in the read-only source pane (mouse or arrow keys).
3. Press **F9**, click the gutter, or click **● Breakpoint**. A red **●** appears in the
   gutter beside that line number, before the code. Expand the file to see its
   **Line N · pending** children; selecting one navigates to that line.
4. Click the red **●** to remove the mark, or click that gutter position on an
   unmarked line to add one. The original toggle button still works.

The red dot stays aligned while scrolling and reappears when you reopen the marked
file. Red indicates requested intent, **not debugger verification**.

## Conditional breakpoints and logpoints

Press **Shift+F9** on a line to open a short breakpoint panel at the bottom of the screen.
The source stays visible above it, and its title shows the file, line and code. It has two
one-line fields:

- **if** (condition): the debugger stops only when the expression is true in the target's
  language, for example `user_id == 42` (Python, Go) or `userId === 42` (Node).
- **log** (log message): makes a **logpoint**. It writes the message to the debug output and
  never stops. `{expression}` parts are replaced with their value, for example
  `order {order.id} received`. With a condition too, it logs only when the condition holds.
  An expression may contain braces, such as `{ {id: user.id}.id }`; an empty `{}` or an
  unclosed `{` is kept as text.

**Enter** saves, and leaving both fields empty makes a plain breakpoint. **Escape** keeps
the breakpoint unchanged. To remove a breakpoint use **F9**, as for any other: on a line with
a condition or log message it removes the breakpoint together with them.

| Condition | Log message | Result |
|---|---|---|
| set | empty | Stops only when the condition is true. |
| empty | set | Never stops; writes the message every time the line runs. |
| set | set | Never stops; writes the message only when the condition is true. |
| empty | empty | Plain breakpoint: always stops. |

Each line with a condition or log message also shows them in dim text after its code, for
example `if user_id == 42` or `log: order {order.id} received`, so all of a file's
conditions are visible at a glance. The hint is shortened to fit, and left out when the line
is too long for the view.

With the cursor on a line that has a condition or log message, a read-only panel below the
source shows them and what they do, for example `if answer > 40   stops only when true`. It
disappears on other lines, and **Shift+F9** edits them.

The gutter shows **●** for a plain breakpoint, **◆** for a conditional one and a blue **◇**
for a logpoint. The file's tree entry shows the details, for example
**Line 4 · if user_id == 42 · pending** or **Line 7 · log: order {order.id} received · pending**;
a line with both shows the condition and the message.
Changes apply to an active debug session immediately.

Conditions and log messages work with Python, Go and Node debugging and with Python and Go
attach. The debugger evaluates them, not debugealo, so an invalid expression is handled by
each debugger: Python reports the error in the debug output, Go marks the breakpoint
**unverified** in the file tree, and Node accepts it but never stops there. Node has no
native logpoints: the message is
logged with `console.log` from a condition that never stops, as VS Code does. On Node, a
conditional breakpoint on the very first line of a program can stop once at startup.

They are saved with the breakpoint in `projects/breakpoints.json`, each up to 1000
characters. A file without conditions or log messages keeps exactly the previous format.
Versions of debugealo older than this feature refuse a file that contains them, so
removing them, or going back to plain breakpoints, keeps the file readable by those versions.

Source files and `launch.json` are never edited by this pane. Requested breakpoints use
1-based line numbers, are isolated by project root and file, and persist in the central
`projects/breakpoints.json` beside the Code `launch.json`. Two profiles sharing a root
share its marks. Closing and reopening debugealo restores marks as **pending**; only an
active debugger's current response appears as verified or unverified. Verification is
session-only and is never saved. Marks are not relocated when external edits change line
numbers. Invalid or inaccessible saved state is shown in the source status and is not
overwritten; a failed save leaves the current in-memory marks usable but unsaved.
The original requested line and red gutter dot never move to an adapter's returned line.
This store supports one application writer at a time; concurrent-process coordination
is not provided.

Directories load on expansion, with a preview limit of 2,000 entries per directory.
Symbolic links and junctions are omitted. Source preview supports regular UTF-8 files
(up to 1 MiB); binary, unreadable, oversized and missing files show an error instead.
The preview is not an operating-system sandbox; browse trusted local projects.

## Debug Python with the same profile

1. Use a Python script or module command, for example `["python", "main.py"]` or
   `["python", "-u", "-m", "package.module"]`. Install `debugpy` yourself in that
   profile's interpreter before launching; debugealo never installs it at runtime.
2. Mark an executable source line with **F9**, the button or the gutter, then press **Shift+F5**
   or **Debug**.
   The initial requested breakpoints are sent before the program runs.
3. At a pause, inspect the **Frame / Source / Line** stack and the variables pane.
   Select a stack row (Enter or click) to preview its source and non-expensive scopes.
   A yellow **▶** and a yellow-shaded line identify the execution line independently of
   red breakpoint dots.
4. Use **F10** (Over), **F11** (In), **Shift+F11** (Out), or **F5** (**▶ Continue**). **F5** continues only
   when the profile under the cursor is paused; otherwise it keeps its run-without-debug
   meaning and never starts a second session for that profile.
5. **Stop** ends the owned adapter and target tree, including pending startup.
   Quitting also cancels startup and closes the owned session.

Code retains a separate run or debug context for each saved profile. Select another profile
to view its output, stack, variables, source execution marker, and controls; background events
stay with their owning profile. Starting a profile that already has a live context selects it
instead of spawning a duplicate. **Stop** affects only the selected profile context, and
quitting closes all owned local runs/debuggers while disconnecting (never terminating)
external Go targets. Requested breakpoint intent is shared by project root; adapter
verification and inspection state belong to each debugger context.

Distinct profiles may run, debug, or attach concurrently. A profile name remains pinned to
its live configuration through reload/removal and cannot start a second session under edited
settings until its existing context is retired. The same external Go host/port cannot be
attached through two profiles because remote breakpoint cleanup is shared; a rejected attach
does not create a backend or touch the target. Attach recovery remains explicit and pinned:
there is no automatic reconnect or endpoint probing. Selecting another profile or switching
areas never stops or retargets a live context.
Stack navigation returns to its started profile's root. Switching to Containers preserves
Code work but disables Code launch/step shortcuts there. Focused interactive terminals and
modal dialogs retain their existing shortcut guards.

Debug output is Code-only, attributed to the started profile, and bounded to 2,000
rendered lines. Debug mode uses `internalConsole`: **interactive stdin is not supported**;
use F5 for interactive run-without-debug. Frames, variables and the execution arrow
are invalidated on resume/Stop/exit. Requested breakpoint marks survive.
Stack source paths use the same containment, no-links/junctions, regular UTF-8 and
1 MiB preview checks as file-tree navigation; unsafe or unavailable paths show an error.
This is a preview safeguard, not a sandbox or protection against concurrent filesystem changes.

Unsupported commands (including Python `-c` and npm without an explicit debug target)
and missing adapters show an actionable warning with **no run-mode fallback**, no profile
rewrites and no source edits. Python script/module grammar and installation guidance are in
the [Python backend API and limits](python-debugging.md). Go debugging supports only
`go run main.go [args...]` and `go run . [args...]`; install Delve separately and make
`dlv` available on the application PATH. See the [Go debugging walkthrough and limits](go-debugging.md).
Expressions can be evaluated as [watch expressions](#watch-expressions); interactive debug
stdin remains unsupported.

## Watch expressions

The debug panel has a **Watch** section between the stack and the variables. Type an
expression in **+ Add watch expression** and press **Enter**; it is added to the list for
this project. Select a watch and press **Delete** to remove it. A blank or repeated
expression is not added, and a project keeps up to 100 watches.

Every watch is evaluated again on each pause (a breakpoint or a step) and when you select
another stack frame, in that frame's scope. Without a paused session its value shows `—`.
If an expression fails, its row shows the debugger's error, for example
`⚠ NameError: name 'count' is not defined`, and the other watches keep working.

Watches work with Python, Go and Node debugging and with Python and Go attach. They are
saved per project root in `projects/watches.json`, beside the breakpoints file; values are
never saved.

**A watch runs code in your program.** Evaluating `items.pop()` removes an item on every
pause, and a call with side effects repeats them. As in VS Code, debugealo does not block
such expressions, so prefer reading values over calling functions that change state.

## Attach to an existing Go/Delve target

Use `goAttach` to connect Code to an already running headless Delve DAP server. Code
connects only to loopback and never starts a local adapter, builds a program, launches the
profile command, or owns the target process. Containers remains responsible for starting,
stopping, and inspecting the container.

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

`goAttach` has exactly three required keys: `host` is `127.0.0.1`; `port` is an integer
from 1 through 65535 (a JSON boolean is not an integer); and `remoteRoot` is an absolute
POSIX path without backslashes or `..` path segments. Invalid profiles are reported rather
than rewritten. `command` is optional for attach-only profiles. If supplied, it retains its
ordinary F5 meaning and is never run by attach. F5 on an attach-only profile warns to use
Shift+F5 and does not launch a local process.

1. Start the target/container and its headless Delve server independently in **Containers**.
   The configured endpoint must already be reachable on `127.0.0.1:<port>`.
2. Add the profile above to Code's central `projects/launch.json`, replacing the local
   `workspaceFolder` with the folder containing the matching source tree.
3. Open source, mark pending breakpoints, then press **Shift+F5**. Code shows
   **Connecting**, then **Attached**; the started profile and root remain pinned even if
   another profile is selected, profiles are reloaded, or the user switches areas.
4. At a pause, inspect stack, scopes and variables; use **F5** (Continue), **F10** (Over),
   **F11** (In), and **Shift+F11** (Out). Breakpoints, stack navigation and source previews
   follow the attached profile's local root.
5. Use **Disconnect** or **Stop** to clear this attach session's remote breakpoints and
   leave the target running, even when it was paused. The target is not terminated and the UI
   does not report it as exited. The same external endpoint cannot be attached concurrently
   through two profiles because remote breakpoint cleanup is shared. Local requested marks
   and their stored data are preserved
   and reapplied on reconnect; a transport failure while clearing, resuming, or disconnecting
   shows a warning and reports the target state as unknown. If the transport is lost
   unexpectedly, Code shows **Unexpected disconnect; target state UNKNOWN** and offers an
   explicit **Reconnect** action pinned to the same profile. Marks remain pending until the
   new Delve connection confirms them. No automatic retries or target restarts occur; check
   the endpoint in Containers and click **Reconnect** only when it is available. Deliberate
   Disconnect and local Python/Node debugging do not offer this recovery action.
   Containers independently reports and controls the container lifecycle.

Local `workspaceFolder` maps to remote `remoteRoot` (for example, local `main.go` maps to
`/app/main.go`). Breakpoints are sent with remote paths; returned stack paths are mapped
back into the local root and checked for containment before source preview. The configured
Delve server must be started with compatible source substitution and expose the remote
DAP target. Attach supports breakpoints, stopped state, stack, scopes, variables, step and
continue, and watch expressions. It does not support debug stdin, arbitrary endpoints,
starting/stopping Delve, or target lifecycle management. Target stdout/stderr remain
available through the container's logs; the Code attach session does not present them as
its debug output stream.

## Attach to an existing Python/debugpy target

Use `pythonAttach` to connect Code to a process already listening through `debugpy`, for example
inside a container. It has the same exactly three keys and validation as `goAttach`, and the same
**Shift+F5**, **Disconnect**, **Reconnect** and F5 behavior. A profile cannot declare both. No local
`debugpy` is needed, because Code never starts an adapter or owns the target.

```json
{
  "name": "Python remote",
  "workspaceFolder": "/local/path/to/project",
  "pythonAttach": {
    "host": "127.0.0.1",
    "port": 5678,
    "remoteRoot": "/workspace"
  }
}
```

Start the target with `python -m debugpy --listen 0.0.0.0:5678 ...` and publish that port on host
loopback only, such as `127.0.0.1:5678:5678`: anything that reaches the debug port can run code in
the target. Local `app/main.py` maps to `/workspace/app/main.py`, and stack paths map back. Local
and target sources must match, or breakpoints land on the wrong lines. Disconnect clears this
session's breakpoints and resumes a paused target, which keeps running and can be attached again.
Target output stays in the container's logs. A connection that closes without attaching, such as a
port probe, can end the `debugpy` listener; recreate the container if attach is then refused.

An endpoint can only be attached once at a time, across both attach kinds. Watch expressions
work; debug stdin is not supported. Try the workflow with the
[FastAPI debug example](../examples/fastapi-debug/README.md).

## Debug server-side Node

Use the same breakpoint, stack, variables, step and Continue controls described above.
Node must already be installed; Inspector is built in, so no adapter installation is needed.
Direct commands support `["node", "server.js", "arg"]` (also `.cjs` and `.mjs`),
without Node runtime flags.

For an npm profile, explicitly identify the server script:

```json
{
  "name": "Node API",
  "workspaceFolder": "C:/work/api",
  "command": ["npm", "run", "dev"],
  "nodeDebug": ["node", "server.js", "arg"]
}
```

**F5** runs the original npm command. **Shift+F5** runs the explicit `nodeDebug`
target with an owned loopback Inspector; it does not debug npm itself or infer its scripts.
The optional `nodeDebug` field is accepted only for npm profiles and uses the direct
Node script grammar above. Other profiles need no schema changes.

Node output comes from a PTY: stdout and stderr are merged in order into the debug console.
Interactive debug stdin is not exposed; use F5 when input is required.
Stop and app exit close the owned process tree, including startup in progress.
Browser debugging, TypeScript/source maps, attach and debugging child processes are
not supported. An unsupported target or unavailable runtime reports an error without
silently running without debug.
