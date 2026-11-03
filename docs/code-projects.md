# Register and run code projects centrally

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

Shift+F5 debugging, source browsing and breakpoints are **not implemented yet**.
One profile will serve both run modes; this stage runs without a debugger.
