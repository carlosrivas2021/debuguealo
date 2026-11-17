"""Independent owned-target and public Code UI verification for Go attach."""

import asyncio
import json
import os
import shutil
import socket
from pathlib import Path

import pytest
from test_code_debug_ui import debug_app, rendered

from debugpilot.debugger import GoAttachSession
from debugpilot.storage.code_projects import CodeProject, GoAttach


async def _write_text(path: Path, text: str) -> None:
    await asyncio.to_thread(path.write_text, text)


async def _read_bytes(path: Path) -> bytes:
    return await asyncio.to_thread(path.read_bytes)


async def _exists(path: Path) -> bool:
    return await asyncio.to_thread(path.exists)


async def _changed(path: Path, previous: bytes) -> bool:
    return await _read_bytes(path) != previous


def _delve_executable() -> str | None:
    executable = shutil.which("dlv")
    if executable:
        return executable
    candidate = Path(__file__).resolve().parents[2] / ".tools" / "bin" / "dlv"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


@pytest.mark.skipif(os.name == 'nt', reason='the remote root must be a POSIX path')
@pytest.mark.asyncio
async def test_owned_real_api_and_ui(monkeypatch, tmp_path):
    delve = _delve_executable()
    if delve is None:
        pytest.skip("Delve is unavailable on PATH and in the project .tools/bin directory")

    remote = tmp_path / "remote"
    local = tmp_path / "local"
    await asyncio.to_thread(remote.mkdir)
    await asyncio.to_thread(local.mkdir)
    source_text = (
        "package main\nimport (\"fmt\";\"os\";\"time\")\nfunc main() {\n"
        " answer := 41\n for {\n  fmt.Print(answer)\n"
        "  os.WriteFile(\"ticks\", []byte(time.Now().String()), 0600)\n"
        "  time.Sleep(40*time.Millisecond)\n }\n}\n"
    )
    remote_source = remote / "main.go"
    source = local / "main.go"
    await _write_text(remote_source, source_text)
    await _write_text(source, source_text)
    await _write_text(remote / "go.mod", "module example.invalid/own\n\ngo 1.22\n")
    ticks = remote / "ticks"

    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
        delve,
        "debug",
        "--headless",
        "--accept-multiclient",
        "--api-version=2",
        "--listen",
        f"127.0.0.1:{port}",
        ".",
        cwd=remote,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            **os.environ,
            "GOTOOLCHAIN": "local",
            "GOWORK": "off",
            "GOPROXY": "off",
            "GOSUMDB": "off",
        },
    )
    listening = asyncio.Event()

    async def read_log(stream):
        while line := await stream.readline():
            if b"API server listening at:" in line:
                listening.set()

    readers = [
        asyncio.create_task(read_log(process.stdout)),
        asyncio.create_task(read_log(process.stderr)),
    ]
    session = GoAttachSession(timeout=4)

    async def wait_for(predicate, seconds=4):
        async with asyncio.timeout(seconds):
            while True:
                result = predicate()
                if asyncio.iscoroutine(result):
                    result = await result
                if result:
                    return
                await asyncio.sleep(0.02)

    try:
        await asyncio.wait_for(listening.wait(), 18)
        profile = CodeProject(
            "owned target", local, (), None, GoAttach("127.0.0.1", port, str(remote))
        )
        await session.start(profile, {source: [6]})
        await wait_for(lambda: session.state == "stopped")
        assert session.verified_breakpoints[str(source)][0]["verified"]
        frames = await session.stack()
        assert frames[0]["source"]["path"] == str(source)
        scopes = await session.scopes(frames[0]["id"])
        values = [
            variable
            for scope in scopes
            if not scope.get("expensive")
            for variable in await session.variables(scope["variablesReference"])
        ]
        assert any(value["name"] == "answer" and value["value"] == "41" for value in values)
        await session.set_breakpoints(source, [])
        await session.continue_execution()
        await session.close()
        await wait_for(lambda: _exists(ticks))
        previous = await _read_bytes(ticks)
        await wait_for(lambda: _changed(ticks, previous))

        app, roots, store = debug_app(monkeypatch, tmp_path / "ui")
        ui_source = roots[0] / "main.go"
        await _write_text(ui_source, source_text)
        config = json.loads(await asyncio.to_thread(store.path.read_text, encoding="utf-8"))
        config["configurations"][0].pop("command")
        config["configurations"][0]["goAttach"] = {
            "host": "127.0.0.1",
            "port": port,
            "remoteRoot": str(remote),
        }
        await _write_text(store.path, json.dumps(config))
        original = await _read_bytes(store.path)

        async with app.run_test(size=(140, 52)) as pilot:
            await pilot.click("#area-code")
            await pilot.press("f5")
            assert "Shift+F5" in rendered(app, "#code-run-state")
            assert not app.query_one("#code-terminal").active
            browser = app.query_one("#source-browser")
            assert browser.open_source(roots[0], ui_source, 6)
            await pilot.click("#source-breakpoint")
            await pilot.press("shift+f5")
            await wait_for(lambda: "answer = 41" in rendered(app, "#code-variables"))
            debug = app.query_one("#code-debug")
            ui_session = debug.session
            assert debug.session.verified_breakpoints[str(ui_source)][0]["verified"]
            assert browser.file_path == ui_source
            assert app.query_one("#code-stop").label == "Disconnect"
            app.query_one("#code-projects").move_cursor(row=1)
            await pilot.pause()
            await pilot.click("#area-containers")
            await pilot.click("#area-code")
            await pilot.click("#code-reload")
            assert debug.profile is None
            assert app.query_one("#code-stop").disabled
            assert process.returncode is None
            app.query_one("#code-projects").move_cursor(row=0)
            await pilot.pause()
            assert debug.session is ui_session
            assert debug.profile.root == roots[0]
            assert debug.profile.go_attach.port == port
            stack = app.query_one("#code-stack")
            stack.focus()
            await pilot.press("enter")
            await wait_for(lambda: browser.root_path == roots[0])
            assert browser.file_path == ui_source
            await pilot.click("#source-breakpoint")
            await wait_for(lambda: not debug.session.requested_breakpoints[str(ui_source)])
            await pilot.click("#code-continue")
            await wait_for(lambda: debug.session.state == "running")
            await pilot.click("#code-stop")
            assert "Disconnected" in rendered(app, "#code-run-state")
            assert process.returncode is None
            app.query_one("#code-projects").move_cursor(row=0)
            await pilot.pause()
            await pilot.press("shift+f5")
            await wait_for(lambda: "Attached:" in rendered(app, "#code-run-state"))
            assert await _read_bytes(store.path) == original

        assert process.returncode is None
        previous = await _read_bytes(ticks)
        await wait_for(lambda: _changed(ticks, previous))
    finally:
        await session.close()
        if process.returncode is None:
            process.terminate()
        await asyncio.wait_for(process.wait(), 3)
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
