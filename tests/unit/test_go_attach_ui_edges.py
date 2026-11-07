"""Public UI edge coverage for attach cancellation and source containment."""

import asyncio
import hashlib
import json

import pytest
from test_code_debug_ui import debug_app, rendered
from test_go_attach import DAPPeer


async def _write_text(path, text):
    await asyncio.to_thread(path.write_text, text)


async def _digest(path):
    contents = await asyncio.to_thread(path.read_bytes)
    return hashlib.sha256(contents).digest()


@pytest.mark.asyncio
@pytest.mark.parametrize("quit_startup", [False, True])
async def test_ui_cancel_external_handshake(monkeypatch, tmp_path, quit_startup):
    attach_received = asyncio.Event()
    client_closed = asyncio.Event()
    requests = []

    async def serve(reader, writer):
        try:
            while True:
                header = await reader.readuntil(b"\r\n\r\n")
                length = int(header.split(b":", 1)[1].strip())
                request = json.loads(await reader.readexactly(length))
                requests.append(request)
                command = request["command"]
                if command == "attach":
                    attach_received.set()
                    continue
                await DAPPeer._send(
                    writer,
                    {
                        "type": "response",
                        "request_seq": request["seq"],
                        "command": command,
                        "success": True,
                        "body": {},
                    },
                )
                if command == "disconnect":
                    break
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            client_closed.set()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        app, _roots, store = debug_app(monkeypatch, tmp_path)
        config = json.loads(await asyncio.to_thread(store.path.read_text, encoding="utf-8"))
        config["configurations"][0].pop("command")
        config["configurations"][0]["goAttach"] = {
            "host": "127.0.0.1",
            "port": server.sockets[0].getsockname()[1],
            "remoteRoot": "/app",
        }
        await _write_text(store.path, json.dumps(config))
        original_digest = await _digest(store.path)

        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.click("#area-code")
            await pilot.press("shift+f5")
            await asyncio.wait_for(attach_received.wait(), 2)
            if not quit_startup:
                await pilot.click("#code-stop")

        await asyncio.wait_for(client_closed.wait(), 2)
        disconnects = [request for request in requests if request["command"] == "disconnect"]
        assert [request["arguments"] for request in disconnects] == [
            {"terminateDebuggee": False}
        ]
        assert not any(request["command"] in {"terminate", "launch"} for request in requests)
        assert await _digest(store.path) == original_digest
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["traversal", "symlink"])
async def test_attach_malicious_frame_rejected(monkeypatch, tmp_path, kind):
    app, roots, store = debug_app(monkeypatch, tmp_path)
    secret = tmp_path / "secret.py"
    await _write_text(secret, "PRIVATE_SENTINEL")
    link = roots[0] / "linked.py"
    try:
        await asyncio.to_thread(link.symlink_to, secret)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks is unavailable")

    malicious_path = "/app/../secret.py" if kind == "traversal" else "/app/linked.py"

    class MaliciousPeer(DAPPeer):
        async def _send(self, writer, message):
            if message.get("command") == "stackTrace":
                message["body"]["stackFrames"][0]["source"]["path"] = malicious_path
            await DAPPeer._send(writer, message)

    peer = MaliciousPeer()
    await peer.start()
    try:
        config = json.loads(await asyncio.to_thread(store.path.read_text, encoding="utf-8"))
        config["configurations"][0].pop("command")
        config["configurations"][0]["goAttach"] = {
            "host": "127.0.0.1",
            "port": peer.port,
            "remoteRoot": "/app",
        }
        await _write_text(store.path, json.dumps(config))
        config_digest = await _digest(store.path)
        secret_digest = await _digest(secret)

        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.click("#area-code")
            await pilot.press("shift+f5")
            async with asyncio.timeout(2):
                while "outside the selected project" not in rendered(app, "#source-status"):
                    await pilot.pause(0.02)
            assert app.query_one("#source-text").text == ""
            await pilot.click("#code-stop")

        assert await _digest(store.path) == config_digest
        assert await _digest(secret) == secret_digest
        disconnects = [request for request in peer.requests if request["command"] == "disconnect"]
        assert all(
            request["arguments"] == {"terminateDebuggee": False}
            for request in disconnects
        )
    finally:
        await peer.close()
