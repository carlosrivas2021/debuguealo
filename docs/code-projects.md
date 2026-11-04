# Register, run and debug code projects centrally

Choose **Code**, then **Open code launch.json** (or Ctrl+O / Ctrl+N while in Code).
The terminal editor creates the file only when explicitly requested. Add your profiles,
save and exit; the table reloads. **Reload code profiles** picks up external edits.

The dedicated file is `projects/launch.json` beside DebugPilot's central container
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

## Run without debug

1. Select a profile in **Code** and press **F5** or click **Run (F5)**.
2. Type in the Code terminal for interactive input. **Escape** returns focus to profiles.
3. Click **Stop** to end that Code process tree. After stopping or exit, run again with F5.

Only one Code execution runs at a time. F5 while starting/running does not restart or
launch another process. Changing the selected profile or switching areas does not
retarget or stop the active execution. Reload affects the next run only.
The status line reports `Running`, `Exited: <code>`, `Stopped`, or a startup error.
The terminal retains the last screen after exit; a new run starts with a fresh screen.
Quitting DebugPilot also stops Code execution, including startup in progress.

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
3. Click **Toggle breakpoint at cursor (pending)**. A red **●** appears in the
   gutter beside that line number, before the code. Expand the file to see its
   **Line N · pending** children; selecting one navigates to that line.
4. Click the red **●** to remove the mark, or click that gutter position on an
   unmarked line to add one. The original toggle button still works.

The red dot stays aligned while scrolling and reappears when you reopen the marked
file during the same session. Red indicates requested intent, **not debugger verification**.

Source files are never edited by this pane. Breakpoints use 1-based line numbers,
are isolated by project root and file, and survive switching profiles/areas in the
current app session. They are not saved across restarts or relocated when external
edits change line numbers. Two profiles sharing a root share its breakpoint marks.
**Pending means intent only** until an active Python or Node debugger responds. The file tree
labels adapter feedback separately as **verified**, **unverified**, or a relocated line.
The original requested line and red gutter dot never move to the adapter's returned line.

Directories load on expansion, with a preview limit of 2,000 entries per directory.
Symbolic links and junctions are omitted. Source preview supports regular UTF-8 files
(up to 1 MiB); binary, unreadable, oversized and missing files show an error instead.
The preview is not an operating-system sandbox; browse trusted local projects.

## Debug Python with the same profile

1. Use a Python script or module command, for example `["python", "main.py"]` or
   `["python", "-u", "-m", "package.module"]`. Install `debugpy` yourself in that
   profile's interpreter before launching; DebugPilot never installs it at runtime.
2. Mark an executable source line, then press **Shift+F5** or **Debug (Shift+F5)**.
   The initial requested breakpoints are sent before the program runs.
3. At a pause, inspect the **Frame / Source / Line** stack and the variables pane.
   Select a stack row (Enter or click) to preview its source and non-expensive scopes.
   A yellow **▶** identifies the execution line independently of red breakpoint dots.
4. Use **Over F10**, **In F11**, **Out Shift+F11**, or **Continue**. Continue is a
   button, not F5. **F5 always runs without debug**; it never resumes a debugger.
5. **Stop** ends the owned adapter and target tree, including pending startup.
   Quitting also cancels startup and closes the owned session.

Only one Code run **or** debug session is active. Stop before changing modes or
starting another profile. Selecting another profile, reloading configuration, or
switching areas never retargets the running session, its output, or Stop. Stack
navigation returns to the started profile's root, even if another row is selected.
Breakpoint edits synchronize only when they belong to that started root; marks in
other roots remain local pending intent for the next launch. Switching to Containers
preserves Code work but disables Code launch/step shortcuts there. Focused interactive
terminals and modal dialogs retain their existing shortcut guards.

Debug output is Code-only, attributed to the started profile, and bounded to 2,000
rendered lines. Debug mode uses `internalConsole`: **interactive stdin is not supported**;
use F5 for interactive run-without-debug. Frames, variables and the execution arrow
are invalidated on resume/Stop/exit. Requested breakpoint marks survive.
Stack source paths use the same containment, no-links/junctions, regular UTF-8 and
1 MiB preview checks as file-tree navigation; unsafe or unavailable paths show an error.
This is a preview safeguard, not a sandbox or protection against concurrent filesystem changes.

Unsupported commands (including Go, Python `-c`, and npm without an explicit debug target)
and missing adapters show
an actionable warning with **no run-mode fallback**, no profile rewrites and no
source edits. Python script/module grammar and installation guidance are in the
[backend API and limits](python-debugging.md). Go debugging, persistent breakpoints,
attach, expression evaluation and interactive debug stdin remain deferred.

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
