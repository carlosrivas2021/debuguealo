# Register, run and debug code projects centrally

Choose **Code**, then **Open code launch.json** (or Ctrl+O while in Code).
The file is created only when explicitly requested and opens in the built-in editor. Add your
profiles, save with **Ctrl+S** and close with **Esc**; the table reloads. **Reload code profiles**, or **R** in the Code area while the selected profile is stopped, picks up external edits.
While the selected profile runs or debugs, **R** restarts it like VS Code's Restart: it stops the
session, rereads `launch.json`, and launches it again in the same mode. If the stop does not
finish, nothing is relaunched. The footer reads **r Restart** or **r Reload** accordingly.

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

Code is laid out like an IDE: profile names, the file tree and the project's breakpoints on the
left (the tree's root is the selected profile's folder; the **PROFILES** title shows how many
there are), source in
the center, the **Debug** panel (controls, stack, variables) on the right while a debug
session is selected, and the bottom area below: the Code terminal for runs or **Debug output**
for debug sessions. **O** hides or shows the bottom area, the same key that shows the host
terminal in Containers; typing an "o" in a text field or a terminal still types it. The footer lists the shortcuts
available in the current area. Selecting a profile shows one bottom view: its live session,
otherwise the run or debug view you used last for that profile.

Each profile in the list shows its state before the name: **▶** (green) while it runs,
**◉** (yellow) while it debugs, and no icon when it is stopped. The icons follow every
profile, not only the selected one, so a run that exits on its own clears its icon within
half a second.

When the selected profile's folder is inside a Git repository, the right end of the action
bar shows its branch, for example **⎇ main**, or **⎇ detached @ 1a2b3c4** for a detached
HEAD. It is read from the repository's files, so Git does not need to be installed, and it
is hidden for folders outside a repository. While the profile runs or debugs, the bar keeps
the branch it was launched from, even if you check out another branch meanwhile; stop and
launch again to pick up the new one. An idle profile shows the current branch each time you
select it.

Click the branch to switch to another local branch: a list opens with the current one marked
**●**; pick one with **Enter**, or close it with **Escape**. This runs `git switch`, so it needs
Git installed. Uncommitted changes follow Git's own rules: changes that do not conflict with the
other branch are carried over, and a conflicting change makes Git refuse the switch, which then
shows Git's message and leaves everything as it was. Switching is refused while any profile from
the same repository runs or debugs, because its code would change under it. After a switch the
file tree and the open file are read again.

The profile list keeps room for six profiles. Drag the gray line between the profiles and
the files, or press **Alt+Up** / **Alt+Down**, to give either one more rows; the file tree
always keeps at least four.

**Ctrl+Left** and **Ctrl+Right** (or **Alt+Left** and **Alt+Right**, which macOS leaves free)
move focus between the panes in screen order: profiles,
file tree and source, wrapping around at either end; from a button they go to the
profiles. They skip the buttons, and in the source they replace the word jump of the
read-only view. In a text field or while typing into the terminal Ctrl+arrows keep their usual
word movement and Alt+arrows do nothing.

F5 and Shift+F5 never move focus, so the arrow keys keep moving between profiles. Click the
terminal to type into the program; its border turns yellow and reads
**typing — Esc to leave**. **Escape** returns to the profiles, even after the program exited.

## Run without debug

1. Select a profile in **Code** (left sidebar) and press **F5** or click **▶ Run**.
2. Click the Code terminal to type interactive input. **Escape** returns focus to profiles.
3. Press **S** (or click **Stop**) to end that Code process tree. After stopping or exit,
   run again with F5.

While a program runs, the terminal title reads **● running · s stop**. When it stops or ends,
a marker closes its output (`── Stopped ──`, `── Exited: 0 ──`), the cursor disappears and
the title becomes **Terminal · stopped** or **Terminal · exited N**, so a finished service
never looks like it is still waiting. In a text field or while typing into the terminal,
**S** types the letter instead.

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

Commands inherit debugealo's environment, plus the profile's own variables (see
[environment variables](#environment-variables)), and run in their configured folder, using
argv rather than a host shell. On Windows, npm's standard `npm.cmd` entry is resolved to Node plus
`npm-cli.js`; other batch launchers require their underlying executable/script instead.
Missing executables and unavailable PTY support produce errors, not a shell fallback.
Windows uses an owned kill-on-close Job Object; POSIX uses an owned process group.
Remaining descendants are terminated on stop **and when the main command exits**.
Do not use this runner for detached background services intended to survive the profile.

## Environment variables

A profile can add variables for **Run** (F5) and **Debug** (Shift+F5) with two optional fields:

```json
{
  "name": "API",
  "workspaceFolder": "/home/me/api",
  "command": ["python", "main.py"],
  "env": { "API_URL": "http://localhost:8000", "DEBUG": "1" },
  "envFile": ".env"
}
```

- **`env`** sets variables directly. Names use letters, digits and underscores and do not
  start with a digit; values are text, and an empty string is allowed.
- **`envFile`** reads a file relative to the `workspaceFolder`, without `..`. Each line is
  `NAME=value`; blank lines and lines starting with `#` are ignored, `export ` is allowed,
  and a value may be wrapped in single or double quotes. An unquoted value ends at ` #`, so
  `PORT=8000 # api` gives `8000`, while `a#b` and quoted text keep their `#`. Nothing is
  expanded or unescaped: `$HOME` and `\n` stay literal. Prefer it for secrets, so they stay in the project and out of the central
  `launch.json`.

Variables are layered: debugealo's own environment, then `envFile`, then `env`, so `env`
wins. The file is read each time you run or debug, so edits apply without reloading the
profiles. A missing or invalid file stops the run with its name and line number; values are
never shown in errors. A `PATH` set this way also decides which executable runs, for Run and
for Debug (the Python interpreter, Node, Go and Delve).

For Go, Debug passes the variables to the program but not to the build Delve runs, so
build settings such as `GOFLAGS` or `CGO_ENABLED` apply to Run (`go run`) only. The
`envFile` path is checked as written: a symbolic link inside the project can point outside
it, which is allowed because the profile is your own configuration.

They apply to Python, Go and Node runs and debug sessions. Attach profiles (`goAttach`,
`pythonAttach`, `nodeAttach`) reject them: the target already runs in its container, which owns its
environment.

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

## Breakpoints list

The **BREAKPOINTS** section under the file tree lists every breakpoint of the selected
profile's folder, by file and then line, for example `◆ main.py:4 if answer == 41`. Its title
shows how many there are; with none it reads **BREAKPOINTS · F9 adds one**. **Ctrl+Right**
from the file tree (or **Alt+Right**) moves to it.

| Key | Action |
|---|---|
| **Enter** | Open the file at that line, with the cursor on it |
| **Space** | Switch the breakpoint off, or back on |
| **Delete** | Remove the breakpoint, with its condition, log message or hit count |
| **A** | Switch every breakpoint of the project off; when all are off, switch them back on |

A breakpoint that is off keeps its line, condition, log message and hit count, but the
debugger never receives it: it neither stops nor logs. It shows a grey **○** in the list and
the gutter, **(off)** in the list and **off** in the file tree. Switching one off or on applies
to an active debug session right away. **F9** on a line that is off removes it.

While debugging, **▶** marks the row of the paused line shown in the source, so a stop at a
breakpoint shows which one it was.

Lines that are off are saved in `projects/breakpoints.json` as a `disabled` list beside the
file's `lines`. A file with none keeps exactly the previous format; versions of debugealo
before this feature refuse a file that has one, so switching them back on keeps it readable
by those versions.

## Conditional breakpoints and logpoints

Press **Shift+F9** on a line to open a short breakpoint panel below the source, in the same
place as the read-only panel described below. The source stays visible above it, and its
title shows the file, line and code. It has three
one-line fields:

- **if** (condition): the debugger stops only when the expression is true in the target's
  language, for example `user_id == 42` (Python, Go) or `userId === 42` (Node).
- **log** (log message): makes a **logpoint**. It writes the message to the debug output and
  never stops. `{expression}` parts are replaced with their value, for example
  `order {order.id} received`. With a condition too, it logs only when the condition holds.
  An expression may contain braces, such as `{ {id: user.id}.id }`; an empty `{}` or an
  unclosed `{` is kept as text.
- **hit** (hit count): the debugger stops only on the passes that match, counting from 1
  each time the line runs. `5` (or `==5`) stops on the fifth pass, `>=10` from the tenth on,
  `>3`, `<4` and `<=4` compare the same way, and `%3` stops on every third pass. With a log
  message, it logs only on the matching passes.

A line takes a condition **or** a hit count, not both: debugpy and Delve combine the two
differently, so the panel refuses the pair rather than stopping at different times per
language. A logpoint can have either one.

**Enter** saves, and leaving every field empty makes a plain breakpoint. **Escape** keeps
the breakpoint unchanged. To remove a breakpoint use **F9**, as for any other: on a line with
a condition, log message or hit count it removes the breakpoint together with them.

| Condition | Log message | Result |
|---|---|---|
| set | empty | Stops only when the condition is true. |
| empty | set | Never stops; writes the message every time the line runs. |
| set | set | Never stops; writes the message only when the condition is true. |
| empty | empty | Plain breakpoint: always stops. |

A hit count reads like a condition in this table: alone it stops only on the matching
passes, and with a log message it writes the message only on those passes.

Each line with a condition or log message also shows them in dim text after its code, for
example `if user_id == 42`, `log: order {order.id} received` or `hit >=10`, so all of a file's
conditions are visible at a glance. The hint is shortened to fit, and left out when the line
is too long for the view.

With the cursor on a line that has a condition or log message, a read-only panel below the
source shows them and what they do, for example `if answer > 40   stops only when true`. It
disappears on other lines, and **Shift+F9** edits them.

The gutter shows **●** for a plain breakpoint, **◆** for a conditional one (a hit count
counts as one) and a blue **◇** for a logpoint. The file's tree entry shows the details, for example
**Line 4 · if user_id == 42 · pending** or **Line 7 · log: order {order.id} received · pending**;
a line with both shows the condition and the message, and a hit count shows as **hit >=10**.
Changes apply to an active debug session immediately.

Conditions and log messages work with Python, Go and Node debugging and with Python, Go and
Node attach. The debugger evaluates them, not debugealo, so an invalid expression is handled by
each debugger: Python reports the error in the debug output, Go marks the breakpoint
**unverified** in the file tree, and Node accepts it but never stops there. Node has no
native logpoints: the message is
logged with `console.log` from a condition that never stops, as VS Code does. Node has no
native hit counts either: the condition counts passes in a `globalThis.__debugealoHits`
object inside the program, and counting starts again whenever the breakpoints are set. On Node, a
conditional breakpoint on the very first line of a program can stop once at startup.

They are saved with the breakpoint in `projects/breakpoints.json`, each up to 1000
characters; a hit count is saved as `hitCondition`, in its short form such as `>=10`. A file without conditions or log messages keeps exactly the previous format.
Versions of debugealo older than these features refuse a file that contains them (versions
before hit counts also refuse a `hitCondition`), so
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
rendered lines. Frames, variables and the execution arrow
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
Expressions can be evaluated as [watch expressions](#watch-expressions).

### Program input

While a program that Code launched for debugging (Python, Go or Node) is running, a
**Program input** field appears below the debug output; while it is paused, the same line is
the [debug console](#debug-console). **Enter** sends the line to the
program's standard input, as pressing Enter in a terminal would, so `input()`,
`bufio.Reader.ReadString` or `readline` receive it. **Ctrl+D** sends what is in the field, if
anything, and then ends the input, so a program reading until end of input (such as
`sys.stdin.read()` or `io.ReadAll(os.Stdin)`) stops reading; on Windows it types the console's
end of input, Ctrl+Z then Enter. Starting never moves the focus: press **P** to go to the field (or to the Code terminal of a
program run with **F5**). Typing in the field never triggers Code shortcuts; **Esc** leaves it
for the profile list.

For Python and Node, the debug output is what the program's terminal shows: prompts written
straight to the terminal, such as Python's `getpass` prompt, and the terminal's own echo of what
you type, so a password prompt that turns echo off keeps the password hidden. stdout and stderr
are merged in order. Each line starts with its kind, such as `[stdout]`; the profile's
name is in the panel's title, `Debug output · <profile> · Exceptions: <mode>`. For Go, Delve reports the output itself, and the typed line shows as
`[input] text` only while the program's terminal echoes; Windows cannot report that,
so there typed lines never show for Go, to keep passwords out of the output.
Attached processes are not owned by Code, so attach sessions have no program input.

## Change a variable while paused

While a session is paused, select a variable in **Variables** and press **Enter** (or click the
selected row). Its value turns into a field on the same row: type the new value as an expression of the
program's language, such as `42`, `'text'` or `[1, 2]` in Python, and press **Enter**; **Esc**
cancels. The program uses the new value from then on, and the variables and watches are read
again. A value the debugger cannot evaluate or assign shows a warning and changes nothing.

It works for Python, Go and Node, launched or attached, on every variable the pane lists,
including the fields of an expanded variable. Python and Go evaluate a scope variable's value
once to check it before setting it, so an expression with side effects runs twice; Delve
assigns only the value types it supports and reports the others.

## Expand nested variables

A variable with fields (an object, dict, list, struct or map) shows `▸` before its name. With
the cursor on it, **Right** lists its fields under it, indented, and the marker turns into `▾`;
**Left** collapses it again. **Space** does either, as in the file tree. On a field, **Left** moves the cursor to the variable that holds
it. Expanded variables stay expanded when you step, continue to the next pause or change a
value, as long as the same path exists; a new debug run starts collapsed. Nesting opens at most
8 levels deep, so a self-referencing object cannot grow without end.

A row shows only the first line of a value, cut to fit the pane. The whole value of the
variable under the cursor shows below the rows, wrapped, up to six lines with its own scroll.
**C** copies the whole value to the clipboard, which can hold more than the pane: debugpy
shortens nested values (`[{...}]`), so Python copies the whole value like `repr()`, with objects that have no `__repr__` of their
own written as `Customer(name='Ana', address={...})` from their attributes (no property runs); Node copies
objects as indented JSON; Delve cannot run code, so Go copies the value and its fields as an
indented tree, up to 8 levels and 2000 lines.

## Watch expressions

The debug panel has three titled sections: **Call stack**, **Watch** and **Variables**. In
the call stack, frames without a source file (runtime internals such as Node's module
loader) are dimmed so your own functions stand out. Each variable takes one line: a
multi-line value shows its first line followed by `…`, and Node functions show by name,
for example `ƒ crear_mensaje()` or `class Pedido`.

The debug panel has a **Watch** section between the stack and the variables. Type an
expression in **+ Add watch expression** and press **Enter**; it is added to the list for
this project. Select a watch and press **Delete** to remove it. A blank or repeated
expression is not added, and a project keeps up to 100 watches.

Every watch is evaluated again on each pause (a breakpoint or a step) and when you select
another stack frame, in that frame's scope. Without a paused session its value shows `—`.
If an expression fails, its row shows the debugger's error, for example
`⚠ NameError: name 'count' is not defined`, and the other watches keep working.

A watch whose value has fields (an object, dict, list, struct or map) opens like a variable:
`▸` before the expression, **Right** or **Space** to list its fields, **Left** to close them
or go back to the watch, and the whole value of the highlighted row under the list. **C**
copies that value, as in [Variables](#expand-nested-variables). **Delete** removes only a
whole watch, never a field opened under it.

Watches work with Python, Go and Node debugging and with Python, Go and Node attach. They are
saved per project root in `projects/watches.json`, beside the breakpoints file; values are
never saved.

**A watch runs code in your program.** Evaluating `items.pop()` removes an item on every
pause, and a call with side effects repeats them. As in VS Code, debugealo does not block
such expressions, so prefer reading values over calling functions that change state.

## Debug console

The line under the debug output changes with the session: while the program runs it is
**Program input**, and while it is paused it becomes **Evaluate**, since a paused program reads
nothing. If you were typing in one, the keys move to the other. The placeholder names the frame
Evaluate runs in, for example
`Evaluate · Enter runs in main.py:25 · ↑↓ history`: the frame selected in **Call stack**.
Press **:** to go to it, type an expression and press **Enter**. The debug output shows the
line and its result, or the debugger's error:

```text
> len(orders)
3
> total / 0
⚠ ZeroDivisionError: division by zero
```

Python and Go evaluate in the debugger's console context, so statements such as
`total = 99` also run in Python; Node evaluates expressions and assignments alike. An
assignment prints no value: after each line, **Variables** and **Watch** are read again, so its
effect shows there. **↑** and **↓** walk the lines already run in this Debugealo session (up to
100), and **Esc** returns to the profiles.

Like a watch, a console line **runs code in your program**: `orders.pop()` changes it.

## Pause on exceptions

By default the debugger pauses where an **uncaught** exception is raised, before it ends the
program, so you keep the stack, the variables and the watches of the crash. The status line
reads `Paused on exception: ValueError: invalid literal for int() with base 10: 'abc'`, the
debug output adds an `[exception]` line with the whole message, and the execution line marks
where it was raised. **F5** continues, and the program then ends as it would without a debugger.

Press **E** in Code to move the highlighted profile's project to the next mode:

| Mode | Pauses on |
|---|---|
| `uncaught` (default) | Exceptions nothing catches. |
| `all` | Every exception raised, even ones a `try`/`except` (or `catch`) handles. |
| `none` | Nothing; a crash ends the program as in a normal run. |

The mode applies right away to the project's running debug sessions and to the next ones. It
is kept per project in `projects/exceptions.json`; the default `uncaught` is not written. The
debug output's title shows the current mode, for example `Exceptions: uncaught`.

Every debugger supports it, launched or attached. In Go, `uncaught` and `all` both pause on an
unrecovered panic or a fatal runtime error: a panic that `recover` handles never reaches the
debugger. In Python, `all` pauses again in each of your functions an exception leaves.

An exception can stop inside the runtime's own code, outside the project: Go's
`runtime/panic.go`, or Node's `fs` module in the `all` mode. Code then selects the first
frame of the stack whose file is inside the project, so the execution line, the variables
and the watches show your function. The runtime frames stay above it in **Call stack**.
Breakpoints and steps always show the top frame.

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

An endpoint can only be attached once at a time, across all attach kinds. Watch expressions
work; debug stdin is not supported. Try the workflow with the
[FastAPI debug example](../examples/fastapi-debug/README.md).

## Attach to an existing Node Inspector

Use `nodeAttach` to connect Code to a Node process already listening with `--inspect`, for
example inside a container. It has the same exactly three keys and validation as `goAttach`, and
the same **Shift+F5**, **Disconnect**, **Reconnect** and F5 behavior. A profile declares only one
of `goAttach`, `pythonAttach` or `nodeAttach`.

```json
{
  "name": "Node remote",
  "workspaceFolder": "/local/path/to/project",
  "nodeAttach": {
    "host": "127.0.0.1",
    "port": 9229,
    "remoteRoot": "/app"
  }
}
```

Start the target with `node --inspect=0.0.0.0:9229 server.js` and publish that port on host
loopback only, such as `127.0.0.1:9229:9229`: anything that reaches the Inspector can run code in
the target. Code reads the target list from `http://127.0.0.1:<port>/json/list`, requires exactly
one Node target, and connects to its WebSocket on the same port. Local `src/app.js` maps to
`/app/src/app.js`, and stack paths map back; frames outside `remoteRoot` show without a source.
For compiled TypeScript, Code reads the source maps of the local build: a breakpoint in
`src/app.ts` is set on the target's `/app/dist/app.js` line it maps to, and frames map back to
`src/app.ts`. The local build must match the one the target runs.
Local and target sources must match, or breakpoints land on the wrong lines. A target started
with `--inspect-brk` starts on attach and stops at its first line; press **Continue**.

Disconnect removes this session's breakpoints and resumes a paused target, which keeps running
and can be attached again. If the target exits or the connection drops, Code reports the target
state as unknown and offers **Reconnect**. Target output, including logpoint messages, stays in
the container's logs. Worker threads are not supported.

## Debug server-side Node

Use the same breakpoint, stack, variables, step and Continue controls described above.
Node must already be installed; Inspector is built in, so no adapter installation is needed.
Direct commands support `["node", "server.js", "arg"]` (also `.cjs` and `.mjs`),
without Node runtime flags.

### TypeScript

On Node 22.18 or later, a TypeScript script runs directly: `["node", "src/main.ts"]` (also
`.mts` and `.cts`), for **F5** and **Shift+F5**, and in `nodeDebug`. Node removes the type
annotations by replacing them with spaces, so every line keeps its number: breakpoints, the
stack and stepping use the `.ts` lines as written, with no build step and no source maps.
Node only removes syntax that can be erased; `enum`, `namespace` and constructor parameter
properties fail with Node's own syntax error, and `.tsx` is not supported. Older Node versions
cannot run `.ts` files.

### Compiled TypeScript and source maps

For TypeScript compiled with `tsc` and `"sourceMap": true`, debug the compiled entry point,
for example `["node", "dist/main.js"]`, and set breakpoints in the `.ts` sources. When debugging
starts, Code reads the workspace's `*.js.map`, `*.mjs.map` and `*.cjs.map` files (skipping
`node_modules`, `.git`, `.venv`, `venv` and `__pycache__`, up to 2000 maps of 8 MiB each, and
stopping after 100,000 files and folders). A breakpoint on a `.ts` line is set
on the matching line and column of the generated file before that file loads, and the stack,
the paused line and the breakpoint's verified line show the `.ts` file again. A `.ts` line
without generated code, such as an `interface`, stays **unverified**. A paused line of
generated code that maps to nothing, such as the `"use strict";` line `tsc` adds, shows the
`.js` file. Breakpoints in `.js`
files without a map work as before.

Rebuilding while debugging is not picked up: restart the debug session after a build. A
`.ts` launch (`node src/main.ts`) runs the sources directly and ignores any build's maps.
Inline `data:` maps (as `tsx` or `ts-node` produce), bundled output (webpack, esbuild) and
map sources outside the workspace folder are not supported.

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
Type program input in the **Program input** field; see [Program input](#program-input).
Stop and app exit close the owned process tree, including startup in progress.
Browser debugging and debugging child processes are not supported; to debug a Node process you did not start, see
[Attach to an existing Node Inspector](#attach-to-an-existing-node-inspector). An unsupported target or unavailable runtime reports an error without
silently running without debug.
