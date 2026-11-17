"""Distinct Code profiles may own concurrent sessions through the public TUI."""

import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_code_debug_ui import FakeDebug, debug_app, labels, mark, rendered, until
from textual.widgets import Button, DataTable

import debugpilot.terminal.session as terminal_session
from debugpilot.debugger.node import NodeDebugSession
from debugpilot.debugger.python import PythonDebugSession
from debugpilot.storage.code_projects import CodeProject
from debugpilot.terminal.code_session import CodeSession
from debugpilot.tui import code_debug
from debugpilot.tui.code_workspace import CodeWorkspace

# Windows has no process groups, SIGHUP or SIGTERM handlers to wait for: its close is forced.
posix_close = pytest.mark.skipif(
    os.name == "nt", reason="POSIX process groups and termination signals")


@posix_close
async def test_failed_debug_close_retains_owned_cleanup_for_retry(monkeypatch, tmp_path):
    group_present = True
    calls = []

    def fake_killpg(pid, sig):
        calls.append((pid, sig))
        if sig == 0 and not group_present:
            raise ProcessLookupError

    ticks = 0.0

    def monotonic():
        nonlocal ticks
        ticks += 1.0
        return ticks

    monkeypatch.setattr(terminal_session, "os", SimpleNamespace(killpg=fake_killpg))
    monkeypatch.setattr(terminal_session, "time", SimpleNamespace(monotonic=monotonic))

    adapter = CodeSession(lambda _text: None)
    adapter.process = SimpleNamespace(pid=123, poll=lambda: 0, wait=lambda: 0)
    process = adapter.process
    adapter._closed = False
    adapter._exit_notified = False
    adapter._status_dir = tempfile.TemporaryDirectory(dir=tmp_path)
    status_path = Path(adapter._status_dir.name)
    adapter._docker_config = tempfile.TemporaryDirectory(dir=tmp_path)
    docker_path = Path(adapter._docker_config.name)
    reader = asyncio.create_task(asyncio.Event().wait())
    adapter._reader = reader
    session = PythonDebugSession()
    session.state = "running"
    session._adapter = adapter

    expected_error = "Timed out waiting for the owned process group to exit."
    with pytest.raises(TimeoutError, match=f"^{re.escape(expected_error)}$"):
        await session.close()

    assert session.state == "closing"
    assert session._adapter is adapter
    assert adapter.process is process
    assert reader.done()
    assert not await asyncio.to_thread(docker_path.exists)
    assert not await asyncio.to_thread(status_path.exists)

    first_call_count = len(calls)
    with pytest.raises(TimeoutError, match=f"^{re.escape(expected_error)}$"):
        await session.close()
    assert len(calls) > first_call_count
    assert session.state == "closing"
    assert session._adapter is adapter
    assert adapter.process is process

    group_present = False
    await session.close()
    assert session.state == "closed"
    assert session._adapter is None
    assert adapter.process is None
    assert calls[-1] == (123, 0)


async def test_real_python_and_node_targets_are_terminated_by_close(tmp_path):
    python_script = tmp_path / "owned.py"
    node_script = tmp_path / "owned.js"
    python_script.write_text(
        "import os, time\n"
        "print(f'OWNED_PYTHON_PID:{os.getpid()}', flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    node_script.write_text(
        "console.log('OWNED_NODE_PID:' + process.pid);\n"
        "setInterval(() => {}, 1000);\n",
        encoding="utf-8",
    )
    config = tmp_path / "launch.json"
    config.write_text('{"configurations":[]}', encoding="utf-8")
    config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    output = {"python": [], "node": []}
    pid_ready = {name: asyncio.Event() for name in output}

    def capture_output(name, text):
        output[name].append(text)
        label = "OWNED_PYTHON_PID" if name == "python" else "OWNED_NODE_PID"
        if re.search(rf"{label}:(\d+)", "".join(output[name])):
            pid_ready[name].set()

    python = PythonDebugSession(
        on_output=lambda _category, text: capture_output("python", text)
    )
    node = NodeDebugSession(
        on_output=lambda _category, text: capture_output("node", text)
    )
    pids = {}

    def target_pid(name):
        text = "".join(output[name])
        label = "OWNED_PYTHON_PID" if name == "python" else "OWNED_NODE_PID"
        match = re.search(rf"{label}:(\d+)", text)
        return int(match.group(1)) if match else None

    try:
        await python.start(CodeProject("python", tmp_path, (sys.executable, "-u", "owned.py")), {})
        await node.start(CodeProject("node", tmp_path, ("node", "owned.js")), {})
        await asyncio.gather(
            asyncio.wait_for(pid_ready["python"].wait(), 10),
            asyncio.wait_for(pid_ready["node"].wait(), 10),
        )
        pids = {name: target_pid(name) for name in ("python", "node")}
        assert pids["python"] != pids["node"]
        assert config_sha == hashlib.sha256(config.read_bytes()).hexdigest()

        await python.close()
        assert python.state == "closed"
        # debugpy runs its target in a separate process group, so close cannot wait on it.
        assert await _gone_soon(pids["python"]), "Python target survived its completed close"
        await node.close()
        assert node.state == "closed"
        assert await _gone_soon(pids["node"]), "Node target survived its completed close"
        assert config_sha == hashlib.sha256(config.read_bytes()).hexdigest()
    finally:
        await python.close()
        await node.close()
        for pid in pids.values():
            if _pid_exists(pid):
                os.kill(pid, 9)


async def _gone_soon(pid, wait_seconds=5.0):
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while _pid_exists(pid):
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.02)
    return True


def _pid_exists(pid):
    if os.name == "nt":
        # Windows reads signal 0 as CTRL_C_EVENT; ask for the process's exit code instead.
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True



class FakeNodeDebug(FakeDebug):
    async def stack(self):
        return [{"id": 2, "name": "nodeMain", "line": 8,
                 "source": {"path": str(self.profile.root / "server.js")}}]

    async def variables(self, reference):
        return [{"name": "nodeValue", "value": "202", "variablesReference": 0}]


async def test_debug_step_before_backend_creation_is_safe_noop(monkeypatch, tmp_path):
    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "PythonDebugSession", FakeDebug)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        workspace = app.query_one("#code-workspace")
        workspace.debug_selected()
        context = workspace._debug.selected
        assert context.active and context.session is None
        app.action_code_step_over()
        app.action_code_step_in()
        app.action_code_step_out()
        assert context.active and context.session is None
        await workspace.shutdown()


async def test_same_root_debug_contexts_keep_verification_and_inspection_separate(
    monkeypatch, tmp_path
):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    config["configurations"][1]["workspaceFolder"] = str(roots[0])
    store.path.write_text(json.dumps(config), encoding="utf-8")
    class ProfiledFakeDebug(FakeDebug):
        async def variables(self, reference):
            value = "101" if self.profile.name == "one" else "202"
            return [{"name": "answer", "value": value, "variablesReference": 0}]

    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "PythonDebugSession", ProfiledFakeDebug)

    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        browser = app.query_one("#source-browser")
        table = app.query_one("#code-projects", DataTable)
        await mark(pilot, app, line=4)
        await pilot.click("#code-debug-start")
        await until(pilot, lambda: len(FakeDebug.instances) == 1)
        first = FakeDebug.instances[0]
        await until(pilot, lambda: "answer = 101" in rendered(app, "#code-variables"))
        source = str((roots[0] / "main.py").resolve())
        # Unverified in the first context only: the list row shows it there.
        first.verified_breakpoints[source] = [{"verified": False, "line": 4}]
        first.emit("breakpoints")
        await pilot.pause()
        assert "main.py:4 unverified" in labels(browser)[0]

        table.move_cursor(row=1)
        await pilot.pause()
        await pilot.click("#code-debug-start")
        await until(pilot, lambda: len(FakeDebug.instances) == 2)
        second = FakeDebug.instances[1]
        await until(pilot, lambda: "answer = 202" in rendered(app, "#code-variables"))
        assert first is not second and first.profile.root == second.profile.root
        first.on_output("stdout", "FIRST-ONLY")
        await pilot.pause()
        output = app.query_one("#code-debug-output")
        assert "FIRST-ONLY" not in "\n".join(line.text for line in output.lines)
        assert labels(browser)[0].endswith("main.py:4")
        browser.query_one("TextArea").move_cursor((4, 0))
        await pilot.click("#source-breakpoint")
        await until(pilot, lambda: bool(first.updates) and bool(second.updates))
        assert first.updates[-1][1] == (4, 5)
        assert second.updates[-1][1] == (4, 5)
        assert browser.breakpoints(roots[0], roots[0] / "main.py") == (4, 5)
        table.move_cursor(row=0)
        await pilot.pause()
        assert "answer = 101" in rendered(app, "#code-variables")
        assert "main.py:4 unverified" in labels(browser)[0]
        assert "FIRST-ONLY" in "\n".join(
            line.text for line in app.query_one("#code-debug-output").lines
        )
        first.on_output("stdout", "STALE-QUEUED")
        await app.query_one("#code-workspace").stop()
        await pilot.pause()
        assert "STALE-QUEUED" not in "\n".join(
            line.text for line in app.query_one("#code-debug-output").lines
        )
        await app.query_one("#code-workspace").shutdown()


async def test_paused_python_then_node_shift_f5_starts_distinct_profile(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    config["configurations"][1]["command"] = ["node", "server.js"]
    store.path.write_text(json.dumps(config), encoding="utf-8")
    profiles = store.profiles()
    assert len(profiles) == 2
    assert profiles[0].name == "one" and profiles[1].name == "two"
    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "PythonDebugSession", FakeDebug)
    monkeypatch.setattr(code_debug, "NodeDebugSession", FakeNodeDebug)

    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        table = app.query_one("#code-projects", DataTable)
        await until(pilot, lambda: table.row_count == 2)
        table.focus()
        await pilot.click("#code-debug-start")
        await until(pilot, lambda: len(FakeDebug.instances) == 1)
        python_session = FakeDebug.instances[0]
        assert "Debug stopped: one" in rendered(app, "#code-run-state")
        app.action_debug_code()
        await pilot.pause()
        assert len(FakeDebug.instances) == 1  # Re-selecting an active profile is idempotent.

        app.query_one("#code-projects", DataTable).move_cursor(row=1)
        await pilot.pause()
        app.action_debug_code()
        await pilot.pause(0.2)
        assert len(FakeDebug.instances) == 2, (
            f"expected a second distinct-profile session; got {len(FakeDebug.instances)}"
        )

        node_session = FakeDebug.instances[1]
        assert python_session.profile.name == "one"
        assert node_session.profile.name == "two"
        assert python_session is not node_session
        assert not isinstance(python_session, FakeNodeDebug)
        assert isinstance(node_session, FakeNodeDebug)
        assert "Debug stopped: two" in rendered(app, "#code-run-state")
        stack = app.query_one("#code-stack", DataTable)
        assert stack.row_count == 1
        assert "nodeMain" in str(stack.get_row_at(0))
        assert "server.js" in str(stack.get_row_at(0))
        assert "nodeValue = 202" in rendered(app, "#code-variables")

        python_session.on_output("stdout", "PYTHON-ONLY")
        python_session.emit("stopped", threadId=1)
        await pilot.pause()
        output = "\n".join(line.text for line in app.query_one("#code-debug-output").lines)
        assert "PYTHON-ONLY" not in output
        assert "Debug stopped: two" in rendered(app, "#code-run-state")

        await pilot.click("#code-stop")
        assert node_session.closed
        assert not python_session.closed
        app.query_one("#code-projects", DataTable).move_cursor(row=0)
        await pilot.pause()
        assert "Debug stopped: one" in rendered(app, "#code-run-state")
        assert app.query_one("#code-stack", DataTable).row_count == 1
        assert "PYTHON-ONLY" in "\n".join(
            line.text for line in app.query_one("#code-debug-output").lines
        )
        assert app.query_one("#source-browser").root_path == roots[0].resolve()
        await app.query_one("#code-workspace").shutdown()
        assert python_session.closed


async def test_distinct_external_attach_endpoints_coexist_with_local_run(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    config["configurations"][0].pop("command")
    config["configurations"][0]["goAttach"] = {
        "host": "127.0.0.1", "port": 43127, "remoteRoot": "/app"
    }
    config["configurations"][1].pop("command")
    config["configurations"][1]["goAttach"] = {
        "host": "127.0.0.1", "port": 43128, "remoteRoot": "/app"
    }
    store.path.write_text(json.dumps(config), encoding="utf-8")
    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "GoAttachSession", FakeDebug)

    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.click("#code-debug-start")
        await until(pilot, lambda: len(FakeDebug.instances) == 1)
        first = FakeDebug.instances[0]
        app.query_one("#code-projects", DataTable).move_cursor(row=1)
        await pilot.pause()
        app.action_debug_code()
        await until(pilot, lambda: len(FakeDebug.instances) == 2)
        second = FakeDebug.instances[1]
        await until(pilot, lambda: hasattr(second, "profile"))
        assert first.profile.go_attach.port == 43127
        assert second.profile.go_attach.port == 43128
        assert not first.closed and not second.closed
        await pilot.click("#code-stop")
        assert second.closed and not first.closed
        app.query_one("#code-projects", DataTable).move_cursor(row=0)
        await pilot.pause()
        await pilot.click("#code-stop")
        assert first.closed


async def test_same_external_attach_endpoint_is_rejected(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    for profile in config["configurations"]:
        profile.pop("command")
        profile["goAttach"] = {
            "host": "127.0.0.1", "port": 43127, "remoteRoot": "/app"
        }
    store.path.write_text(json.dumps(config), encoding="utf-8")
    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "GoAttachSession", FakeDebug)

    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.click("#code-debug-start")
        await until(pilot, lambda: len(FakeDebug.instances) == 1)
        first = FakeDebug.instances[0]
        app.query_one("#code-projects", DataTable).move_cursor(row=1)
        await pilot.pause()
        app.action_debug_code()
        await pilot.pause()

        assert len(FakeDebug.instances) == 1
        assert not first.closed
        assert "endpoint 127.0.0.1:43127 is already active" in rendered(
            app, "#code-run-state"
        )
        app.query_one("#code-projects", DataTable).move_cursor(row=0)
        await pilot.pause()
        await pilot.click("#code-stop")
        assert first.closed


async def test_two_owned_python_runs_keep_output_and_stop_selected_only(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    for index, root in enumerate(roots, 1):
        (root / "run.py").write_text(
            "import os, time\n"
            f"print('RUN_{index}_PID:' + str(os.getpid()), flush=True)\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        config["configurations"][index - 1]["command"] = [
            sys.executable, "-u", "run.py"
        ]
    store.path.write_text(json.dumps(config), encoding="utf-8")

    alive = _pid_exists

    first_pid = second_pid = None
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        app.action_run_code()
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: "RUN_1_PID:" in pane.render().plain)
        first_pid = int(re.search(r"RUN_1_PID:(\d+)", pane.render().plain).group(1))

        app.query_one("#code-projects", DataTable).move_cursor(row=1)
        await pilot.pause()
        app.action_run_code()
        await until(pilot, lambda: "RUN_2_PID:" in pane.render().plain)
        output = pane.render().plain
        assert "RUN_2_PID:" in output, "second profile did not start its own process"
        second_pid = int(re.search(r"RUN_2_PID:(\d+)", output).group(1))
        assert first_pid != second_pid
        assert alive(first_pid) and alive(second_pid)

        await pilot.click("#code-stop")
        # Windows ends a process a moment after it is told to.
        assert await _gone_soon(second_pid)
        assert alive(first_pid), "stopping the selected profile stopped its sibling"
        app.query_one("#code-projects", DataTable).move_cursor(row=0)
        await pilot.pause()
        assert f"RUN_1_PID:{first_pid}" in pane.render().plain
        assert alive(first_pid)

    assert first_pid is not None and await _gone_soon(first_pid), (
        "quit left an owned run process alive")


async def test_run_and_debug_coexist_but_same_profile_actions_only_select(
    monkeypatch, tmp_path
):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    (roots[0] / "run.py").write_text(
        "import os, time\nprint('RUN_PID:' + str(os.getpid()), flush=True)\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    config["configurations"][0]["command"] = [sys.executable, "-u", "run.py"]
    config["configurations"][1]["command"] = ["node", "server.js"]
    store.path.write_text(json.dumps(config), encoding="utf-8")
    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "PythonDebugSession", FakeDebug)
    monkeypatch.setattr(code_debug, "NodeDebugSession", FakeNodeDebug)

    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        app.action_run_code()
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: "RUN_PID:" in pane.render().plain)
        run_pid = int(re.search(r"RUN_PID:(\d+)", pane.render().plain).group(1))

        app.action_debug_code()  # Shift+F5 on the active run selects it.
        await pilot.pause()
        assert not FakeDebug.instances
        assert pane.active and f"RUN_PID:{run_pid}" in pane.render().plain

        app.query_one("#code-projects", DataTable).move_cursor(row=1)
        await pilot.pause()
        app.action_debug_code()
        await pilot.pause(0.2)
        assert len(FakeDebug.instances) == 1, "distinct-profile debug was blocked by a run"
        node_session = FakeDebug.instances[0]
        assert node_session.profile.name == "two"
        assert _pid_exists(run_pid)

        app.action_run_code()  # F5 on active debug selects; it doesn't run Node.
        await pilot.pause()
        assert len(FakeDebug.instances) == 1
        assert not pane.active
        assert not node_session.closed

        app.query_one("#code-projects", DataTable).move_cursor(row=0)
        await pilot.pause()
        app.action_debug_code()  # Shift+F5 returns to the existing run context.
        assert len(FakeDebug.instances) == 1
        assert pane.display and pane.active and f"RUN_PID:{run_pid}" in pane.render().plain
        app.action_run_code()  # F5 also reselects the existing run, without duplication.
        assert pane.active and f"RUN_PID:{run_pid}" in pane.render().plain
        await pilot.click("#code-stop")
        assert not pane.active
        assert not node_session.closed
        app.query_one("#code-projects", DataTable).move_cursor(row=1)
        await pilot.pause()
        await pilot.click("#code-stop")
        assert node_session.closed


async def test_same_name_config_edit_cannot_create_cross_mode_session(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "PythonDebugSession", FakeDebug)
    marker = roots[0] / "run-started"
    (roots[0] / "run.py").write_text(
        f"from pathlib import Path; Path({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )

    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("shift+f5")
        await until(pilot, lambda: len(FakeDebug.instances) == 1)
        original = FakeDebug.instances[0]
        config = json.loads(store.path.read_text(encoding="utf-8"))
        config["configurations"][0]["command"] = [sys.executable, "run.py"]
        store.path.write_text(json.dumps(config), encoding="utf-8")
        await pilot.click("#code-reload")
        app.action_run_code()
        await pilot.pause(0.2)

        assert not marker.exists(), "edited same-name profile launched across active debug"
        assert not app.query_one("#code-terminal").active
        assert len(FakeDebug.instances) == 1
        assert original.profile.command == (sys.executable, "-u", "main.py")


async def test_live_profile_stays_pinned_through_edit_removal_and_bad_reload(
    monkeypatch, tmp_path
):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "PythonDebugSession", FakeDebug)
    async with app.run_test(size=(120, 45)) as pilot:
        table = app.query_one("#code-projects", DataTable)
        workspace = app.query_one("#code-workspace")
        reload_completions = []

        registered_handlers = dict(CodeWorkspace.__dict__["_decorated_handlers"])
        pressed_handlers = list(registered_handlers[Button.Pressed])
        for index, (handler, selectors) in enumerate(pressed_handlers):
            if handler.__name__ == "reload_profiles":
                @wraps(handler)
                def traced_reload(instance, _handler=handler):
                    if instance is not workspace:
                        return _handler(instance)
                    result = _handler(instance)
                    reload_completions.append(result)
                    return result

                pressed_handlers[index] = (traced_reload, selectors)
                break
        registered_handlers[Button.Pressed] = pressed_handlers
        monkeypatch.setattr(CodeWorkspace, "_decorated_handlers", registered_handlers)

        async def click_reload(label):
            button = app.query_one("#code-reload", Button)
            await until(
                pilot,
                lambda: button.display and not button.disabled
                and not button.has_class("-active"),
            )
            completed_before = len(reload_completions)
            clicked = await pilot.click("#code-reload")
            assert clicked, f"Reload button click did not dispatch: {label}"
            await until(pilot, lambda: len(reload_completions) > completed_before)
            return clicked

        await pilot.click("#area-code")
        await pilot.click("#code-debug-start")
        await until(pilot, lambda: len(FakeDebug.instances) == 1)
        session = FakeDebug.instances[0]
        original_root = session.profile.root
        config = json.loads(store.path.read_text(encoding="utf-8"))
        config["configurations"][0]["workspaceFolder"] = str(roots[1])
        config["configurations"][0]["command"] = [sys.executable, "replacement.py"]
        store.path.write_text(json.dumps(config), encoding="utf-8")
        await click_reload("edited-profile-reload")
        table = app.query_one("#code-projects", DataTable)
        assert "one" in [row.key.value for row in table.ordered_rows]
        assert session.profile.root == original_root
        assert session.profile.command == (sys.executable, "-u", "main.py")

        config["configurations"] = config["configurations"][1:]
        store.path.write_text(json.dumps(config), encoding="utf-8")
        await click_reload("removed-profile-reload")
        assert table.row_count == 2
        assert "one" in [row.key.value for row in table.ordered_rows]
        store.path.write_text("{ malformed", encoding="utf-8")
        malformed_bytes = store.path.read_bytes()
        await click_reload("malformed-reload")
        assert table.row_count == 1
        assert "one" in [row.key.value for row in table.ordered_rows]
        assert not app.query_one("#code-stop").disabled
        assert store.path.read_bytes() == malformed_bytes
        await pilot.click("#code-stop")
        assert session.closed
        await click_reload("empty-reload-after-stop")
        assert table.row_count == 0
        assert "one" not in [row.key.value for row in table.ordered_rows]
        assert store.path.read_bytes() == malformed_bytes

        config["configurations"] = [{
            "name": "one", "workspaceFolder": str(roots[1]),
            "command": [sys.executable, "replacement.py"],
        }]
        store.path.write_text(json.dumps(config), encoding="utf-8")
        await click_reload("restored-reload")
        current_bytes = store.path.read_bytes()
        table.focus()
        await pilot.press("home")
        await pilot.pause()
        debug_button = app.query_one("#code-debug-start")
        visible_geometry = (
            debug_button.display, debug_button.disabled,
            debug_button.region.width, debug_button.region.height,
        )
        assert 0 <= table.cursor_row < table.row_count, (
            f"restored profile selection has cursor {table.cursor_row} with "
            f"{table.row_count} visible rows"
        )
        selected_name = table.ordered_rows[table.cursor_row].key.value
        assert selected_name == "one", f"restart selected {selected_name!r}, expected 'one'"
        assert visible_geometry[0] and not visible_geometry[1] and all(visible_geometry[2:]), (
            f"restart button not interactable: {visible_geometry}"
        )
        clicked = await pilot.click("#code-debug-start")
        assert clicked, "public Debug button click did not dispatch"
        await until(pilot, lambda: len(FakeDebug.instances) == 2)
        replacement = FakeDebug.instances[1]
        assert replacement.profile.root == roots[1]
        assert replacement.profile.command == (sys.executable, "replacement.py")
        assert store.path.read_bytes() == current_bytes
        await app.query_one("#code-workspace").shutdown()


async def test_shutdown_joins_public_stop_not_message_pump(monkeypatch, tmp_path):
    app, _roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    config["configurations"][0].pop("command")
    config["configurations"][0]["goAttach"] = {
        "host": "127.0.0.1", "port": 43127, "remoteRoot": "/app"
    }
    store.path.write_text(json.dumps(config), encoding="utf-8")
    class FakeGoAttach(FakeDebug):
        def __init__(self, on_event, on_output):
            super().__init__(on_event, on_output)
            self.close_entered = asyncio.Event()
            self.close_gate = None

        async def close(self):
            if self.close_gate is not None:
                self.close_entered.set()
                await self.close_gate.wait()
            await super().close()

    FakeGoAttach.instances = []
    monkeypatch.setattr(code_debug, "GoAttachSession", FakeGoAttach)
    gate = asyncio.Event()
    click = shutdown = None
    async with app.run_test(size=(120, 45)) as pilot:
        try:
            await pilot.click("#area-code")
            app.action_debug_code()
            await until(pilot, lambda: len(FakeGoAttach.instances) == 1)
            session = FakeGoAttach.instances[0]
            session.close_gate = gate
            workspace = app.query_one("#code-workspace")
            click = asyncio.create_task(pilot.click("#code-stop"))
            await asyncio.wait_for(session.close_entered.wait(), 3)
            shutdown = asyncio.create_task(workspace.shutdown())
            done, _ = await asyncio.wait([shutdown], timeout=1)
            assert not done, "shutdown abandoned owned attach cleanup"
            gate.set()
            done, _ = await asyncio.wait([shutdown], timeout=1)
            assert session.closed, "released gate did not finish attach cleanup"
            assert shutdown in done, "shutdown awaited message-pump lifetime after cleanup"
            await shutdown
        finally:
            gate.set()
            pending = [task for task in (click, shutdown) if task is not None]
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


async def test_run_shutdown_joins_public_stop_not_message_pump(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    (roots[0] / "run.py").write_text("import time; time.sleep(30)\n", encoding="utf-8")
    config = json.loads(store.path.read_text(encoding="utf-8"))
    config["configurations"][0]["command"] = [sys.executable, "run.py"]
    store.path.write_text(json.dumps(config), encoding="utf-8")
    gate = asyncio.Event()
    entered = asyncio.Event()
    stop = shutdown = None
    async with app.run_test(size=(120, 45)) as pilot:
        try:
            await pilot.click("#area-code")
            app.action_run_code()
            await until(pilot, lambda: app.query_one("#code-terminal").active)
            context = app.query_one("#code-terminal").selected_context
            session = context.session
            close = session.close_session

            async def gated_close():
                entered.set()
                await gate.wait()
                await close()

            session.close_session = gated_close
            stop = asyncio.create_task(pilot.click("#code-stop"))
            await asyncio.wait_for(entered.wait(), 3)
            shutdown = asyncio.create_task(app.query_one("#code-workspace").shutdown())
            done, _ = await asyncio.wait([shutdown], timeout=1)
            assert not done, "shutdown abandoned owned run cleanup"
            gate.set()
            done, _ = await asyncio.wait([shutdown], timeout=1)
            assert session._closed, "released gate did not finish run cleanup"
            assert shutdown in done, "shutdown awaited message-pump lifetime after cleanup"
            await shutdown
        finally:
            gate.set()
            pending = [task for task in (stop, shutdown) if task is not None]
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


async def test_retired_debug_cannot_pin_fresh_run_root(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "PythonDebugSession", FakeDebug)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    (roots[1] / "run.py").write_text(
        "import os, time; print('FRESH_ROOT_PID:' + str(os.getpid()), flush=True); "
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    config["configurations"][1]["command"] = [sys.executable, "-u", "run.py"]
    store.path.write_text(json.dumps(config), encoding="utf-8")
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.click("#code-debug-start")
        await until(pilot, lambda: len(FakeDebug.instances) == 1)
        old_debug = FakeDebug.instances[0]
        await until(pilot, lambda: "answer = 41" in rendered(app, "#code-variables"))
        old_debug.on_output("stdout", "RETIRED_OUTPUT")
        output = app.query_one("#code-debug-output")
        await until(
            pilot,
            lambda: any("RETIRED_OUTPUT" in line.text for line in output.lines),
        )
        await pilot.click("#code-stop")
        config["configurations"][0]["workspaceFolder"] = str(roots[1])
        config["configurations"][0]["command"] = [sys.executable, "-u", "run.py"]
        store.path.write_text(json.dumps(config), encoding="utf-8")
        unchanged_bytes = store.path.read_bytes()
        await pilot.click("#code-reload")
        table = app.query_one("#code-projects", DataTable)
        table.move_cursor(row=0)
        await pilot.pause()
        app.action_run_code()
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: "FRESH_ROOT_PID:" in pane.render().plain)
        pid = int(re.search(r"FRESH_ROOT_PID:(\d+)", pane.render().plain).group(1))
        assert _pid_exists(pid)
        assert app.query_one("#source-browser").root_path == roots[1].resolve()
        assert store.path.read_bytes() == unchanged_bytes
        table.move_cursor(row=1)
        await pilot.pause()
        table.move_cursor(row=0)
        await pilot.pause()
        assert app.query_one("#source-browser").root_path == roots[1].resolve()
        assert _pid_exists(pid)
        assert app.query_one("#code-workspace")._debug.selected is not None
        assert app.query_one("#code-workspace")._debug.selected.session is old_debug
        assert any(
            "RETIRED_OUTPUT" in line.text
            for line in app.query_one("#code-debug-output").lines
        )
        await app.query_one("#code-workspace").shutdown()
        assert await _gone_soon(pid), "shutdown left fresh owned process alive"


async def test_pending_run_stop_is_profile_local_and_late_exit_is_attributed(
    monkeypatch, tmp_path
):
    from debugpilot.terminal.code_session import CodeSession

    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    first_done = roots[0] / "done"
    for index, root in enumerate(roots, 1):
        marker = first_done if index == 1 else root / "done"
        script = root / "run.py"
        script.write_text(
            f"from pathlib import Path; print('RUN_{index}_DONE', flush=True); "
            f"Path({str(marker)!r}).touch()\n",
            encoding="utf-8",
        )
        config["configurations"][index - 1]["command"] = [
            sys.executable, "-u", "run.py"
        ]
    store.path.write_text(json.dumps(config), encoding="utf-8")
    entered = {root.name: asyncio.Event() for root in roots}
    release = {root.name: asyncio.Event() for root in roots}
    original = CodeSession.open_command

    async def gated_open(session, command, cwd, *args):
        key = Path(cwd).name
        entered[key].set()
        await release[key].wait()
        await original(session, command, cwd, *args)

    monkeypatch.setattr(CodeSession, "open_command", gated_open)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        app.action_run_code()
        await asyncio.wait_for(entered[roots[0].name].wait(), 3)
        app.query_one("#code-projects", DataTable).move_cursor(row=1)
        await pilot.pause()
        app.action_run_code()
        await pilot.pause(0.2)
        assert entered[roots[1].name].is_set(), "second profile startup was globally blocked"

        await pilot.click("#code-stop")
        assert "Stopped" in rendered(app, "#code-run-state")
        release[roots[1].name].set()
        await pilot.pause(0.1)
        assert not (roots[1] / "done").exists(), "stopped startup later launched its process"
        release[roots[0].name].set()
        await until(pilot, first_done.exists)
        await pilot.pause()
        assert "Stopped" in rendered(app, "#code-run-state"), (
            "background profile completion overwrote selected profile status"
        )
        pane = app.query_one("#code-terminal")
        assert "RUN_1_DONE" not in pane.render().plain
        app.query_one("#code-projects", DataTable).move_cursor(row=0)
        await pilot.pause()
        assert "RUN_1_DONE" in pane.render().plain


async def _open_real_target(tmp_path, source):
    script = tmp_path / "target.py"
    script.write_text(source, encoding="utf-8")
    output = []
    session = CodeSession(output.append)
    await session.open_command((sys.executable, "-u", str(script)), tmp_path, 24, 80)
    for _ in range(500):
        if "READY" in "".join(output):
            return session, output
        await asyncio.sleep(0.02)
    await session.close_session()
    pytest.fail("target never reported READY")


@posix_close
async def test_close_lets_target_finish_its_graceful_shutdown(tmp_path):
    marker = tmp_path / "clean"
    session, _output = await _open_real_target(tmp_path, (
        "import signal, sys, time\n"
        "def finish(*_):\n"
        "    time.sleep(0.3)\n"
        f"    open({str(marker)!r}, 'w').close()\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGHUP, finish)\n"
        "signal.signal(signal.SIGTERM, finish)\n"
        "print('READY', flush=True)\n"
        "time.sleep(30)\n"
    ))
    await session.close_session()
    assert marker.exists(), "close killed the target during its graceful shutdown"
    assert session.process is None


@posix_close
async def test_close_forces_target_that_ignores_termination(tmp_path):
    session, output = await _open_real_target(tmp_path, (
        "import os, signal, time\n"
        "signal.signal(signal.SIGHUP, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print(f'READY:{os.getpid()}:', flush=True)\n"
        "time.sleep(30)\n"
    ))
    pid = int(re.search(r"READY:(\d+):", "".join(output)).group(1))
    await session.close_session()
    assert not _pid_exists(pid), "close left a target that ignored termination"
    assert session.process is None


CLOSE_FAILURE = "Timed out waiting for the owned process group to exit."


async def _click_when_ready(pilot, app, selector):
    # A Button ignores clicks while it shows its brief "-active" press effect.
    button = app.query_one(selector, Button)
    await until(
        pilot,
        lambda: button.display and not button.disabled and not button.has_class("-active"),
    )
    assert await pilot.click(selector)


async def test_failed_run_stop_keeps_app_and_sibling_and_can_be_retried(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    for index, root in enumerate(roots, 1):
        (root / "run.py").write_text(
            f"import time\nprint('RUN_{index}_UP', flush=True)\ntime.sleep(30)\n",
            encoding="utf-8",
        )
        config["configurations"][index - 1]["command"] = [sys.executable, "-u", "run.py"]
    store.path.write_text(json.dumps(config), encoding="utf-8")

    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        app.action_run_code()
        workspace = app.query_one("#code-workspace")
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: "RUN_1_UP" in pane.render().plain)
        app.query_one("#code-projects", DataTable).move_cursor(row=1)
        await pilot.pause()
        app.action_run_code()
        await until(pilot, lambda: "RUN_2_UP" in pane.render().plain)
        sibling, failing = pane.contexts["one"], pane.selected_context
        assert sibling is not failing
        real_close = failing.session.close_session
        failures = [TimeoutError(CLOSE_FAILURE)]

        async def fail_once():
            if failures:
                raise failures.pop()
            await real_close()

        failing.session.close_session = fail_once
        await _click_when_ready(pilot, app, "#code-stop")
        await pilot.pause()

        assert app.is_running
        assert failing.active and not failing.stopping
        assert not app.query_one("#code-stop").disabled
        assert "Stop incomplete" in str(workspace._run_state.render())
        assert sibling.active

        context, created = pane.prepare_profile(failing.profile)
        assert context is failing and not created, "failed close lost its owned session"

        await _click_when_ready(pilot, app, "#code-stop")
        await until(pilot, lambda: "Stopped" in str(workspace._run_state.render()))
        assert not failing.active
        assert sibling.active


async def test_failed_close_does_not_skip_other_profiles_on_shutdown(monkeypatch, tmp_path):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    config = json.loads(store.path.read_text(encoding="utf-8"))
    for index, root in enumerate(roots, 1):
        (root / "run.py").write_text(
            f"import time\nprint('RUN_{index}_UP', flush=True)\ntime.sleep(30)\n",
            encoding="utf-8",
        )
        config["configurations"][index - 1]["command"] = [sys.executable, "-u", "run.py"]
    store.path.write_text(json.dumps(config), encoding="utf-8")

    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        app.action_run_code()
        workspace = app.query_one("#code-workspace")
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: "RUN_1_UP" in pane.render().plain)
        app.query_one("#code-projects", DataTable).move_cursor(row=1)
        await pilot.pause()
        app.action_run_code()
        await until(pilot, lambda: "RUN_2_UP" in pane.render().plain)
        first, second = pane.contexts["one"], pane.selected_context
        second_session = second.session
        real_close = first.session.close_session
        failures = [TimeoutError(CLOSE_FAILURE)]

        async def fail_once():
            if failures:
                raise failures.pop()
            await real_close()

        first.session.close_session = fail_once
        await workspace.shutdown()

        assert second_session.process is None, "failed close skipped the next profile"
        assert first.active
        await pane.close_context(first)
        assert first.session.process is None


async def test_failed_debug_stop_keeps_app_and_can_be_retried(monkeypatch, tmp_path):
    class FailsOnceDebug(FakeDebug):
        failures = [TimeoutError(CLOSE_FAILURE)]

        async def close(self):
            if self.failures:
                raise self.failures.pop()
            await super().close()

    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    FakeDebug.instances = []
    monkeypatch.setattr(code_debug, "PythonDebugSession", FailsOnceDebug)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.click("#code-debug-start")
        await until(pilot, lambda: len(FakeDebug.instances) == 1)
        session = FakeDebug.instances[0]
        workspace = app.query_one("#code-workspace")

        await _click_when_ready(pilot, app, "#code-stop")
        await pilot.pause()

        assert app.is_running
        assert "Stop incomplete" in str(workspace._run_state.render())
        assert not app.query_one("#code-stop").disabled
        assert not session.closed

        await _click_when_ready(pilot, app, "#code-stop")
        await until(pilot, lambda: session.closed)
        assert "Stopped" in str(workspace._run_state.render())
