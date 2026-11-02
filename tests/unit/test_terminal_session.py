from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import debugpilot.terminal.session as session_module
from debugpilot.core.models import ContainerInfo
from debugpilot.storage.config import Settings
from debugpilot.terminal import TerminalSession, TerminalUnavailable


def container(state: str = "running", identity: str = "a" * 64) -> ContainerInfo:
    return ContainerInfo(
        id=identity, name="sample", image="example", state=state,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_container_open_pins_local_endpoint_without_host_workdir_or_docker_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    async def fake_open(self, argv, cwd, dimensions, env=None):
        captured.update(argv=argv, cwd=cwd, dimensions=dimensions, env=env)

    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    monkeypatch.setenv("DOCKER_CONFIG", "/sensitive/config")
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.invalid:2376")
    monkeypatch.setattr(session_module.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(TerminalSession, "_open", fake_open)
    session = TerminalSession(lambda _text: None)

    await session.open_container(container(), "unix:///var/run/docker.sock", tmp_path)

    argv = captured["argv"]
    env = captured["env"]
    assert isinstance(argv, list)
    assert argv == [
        "/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "exec", "-it",
        "a" * 64, "/bin/sh",
    ]
    assert captured["cwd"] == tmp_path
    assert all(key not in env for key in ("DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_HOST"))
    await session.close_session()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint", ["tcp://remote.invalid:2376", "npipe:////remote/pipe/docker_engine", ""]
)
async def test_container_rejects_nonlocal_endpoint_without_starting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, endpoint: str
) -> None:
    called = False

    async def fake_open(self, *_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(TerminalSession, "_open", fake_open)
    session = TerminalSession(lambda _text: None)
    with pytest.raises((TerminalUnavailable, ValueError)):
        await session.open_container(container(), endpoint, tmp_path)
    assert called is False
    assert session.process is None


@pytest.mark.asyncio
@pytest.mark.parametrize("state,identity", [("exited", "a" * 64), ("running", "--help")])
async def test_container_rejects_stopped_or_nonfull_id_without_starting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: str, identity: str
) -> None:
    async def should_not_start(self, *_args, **_kwargs):
        pytest.fail("invalid container must not start a process")

    monkeypatch.setattr(TerminalSession, "_open", should_not_start)
    session = TerminalSession(lambda _text: None)
    with pytest.raises(TerminalUnavailable):
        await session.open_container(
            container(state, identity), "unix:///var/run/docker.sock", tmp_path
        )
    assert session.process is None
    assert session._reader is None


@pytest.mark.asyncio
async def test_public_host_open_uses_real_controlling_pty_and_decodes_split_utf8(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX controlling-TTY proof requires a native POSIX runner")
    observed: list[str] = []
    ready = asyncio.Event()
    code = (
        "import os,sys,time; "
        "os.write(1,b'\\xc3');time.sleep(.03);os.write(1,b'\\xa9'); "
        "print(' TTY='+str(os.isatty(0))+' FG='+str(os.tcgetpgrp(0)==os.getpgrp()),flush=True)"
    )
    monkeypatch.setattr(session_module, "_host_argv", lambda: [sys.executable, "-c", code])
    session = TerminalSession(lambda text: (observed.append(text), ready.set()))

    try:
        await session.open_host(tmp_path, rows=4, columns=12)
        await asyncio.wait_for(ready.wait(), timeout=3)
        await asyncio.sleep(0.1)
    finally:
        await session.close_session()

    transcript = "".join(observed)
    assert "é TTY=True FG=True" in transcript
    assert session.process is None
    assert session._fd is None
    assert session._reader is None
    assert session._closed


@pytest.mark.asyncio
async def test_host_directory_is_validated_before_process_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    def should_not_start(self, *_args, **_kwargs):
        pytest.fail("missing directory must not start")

    monkeypatch.setattr(session_module, "_host_argv", lambda: ["bash.exe", "-i"])
    monkeypatch.setattr(TerminalSession, "_open_posix", should_not_start)
    session = TerminalSession(lambda _text: None)
    with pytest.raises(TerminalUnavailable, match="working directory"):
        await session.open_host(tmp_path / "missing")
    assert session.process is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunks", [(b"\xc3", b"\xa9", b""), (b"\xc3\xa9", b"")], ids=["split", "whole"]
)
async def test_decoded_empty_chunk_is_not_terminal_eof(monkeypatch, tmp_path, chunks):
    if os.name != "posix":
        pytest.skip("This deterministic adapter exercises the POSIX reader")
    observed = []
    exits = []
    exited = asyncio.Event()
    pending = iter(chunks)
    fake_fd = -12345
    real_read = os.read
    real_close = os.close

    class FinishedProcess:
        def wait(self):
            return 0

    def open_adapter(self, argv, cwd, dimensions, env):
        self.process = FinishedProcess()
        self._fd = fake_fd

    def read_adapter(fd, size):
        return next(pending) if fd == fake_fd else real_read(fd, size)

    def close_adapter(fd):
        if fd != fake_fd:
            real_close(fd)

    def on_exit():
        exits.append("exited")
        exited.set()

    monkeypatch.setattr(session_module, "_host_argv", lambda: [sys.executable])
    monkeypatch.setattr(TerminalSession, "_open_posix", open_adapter)
    monkeypatch.setattr(session_module.os, "read", read_adapter)
    monkeypatch.setattr(session_module.os, "close", close_adapter)
    session = TerminalSession(on_output=observed.append, on_exit=on_exit)
    try:
        await session.open_host(tmp_path)
        await asyncio.wait_for(exited.wait(), timeout=2)
        assert observed == ["é"]
        await session.close_session()
        await session.close_session()
        assert exits == ["exited"]
    finally:
        await session.close_session()


def test_settings_endpoint_validation_is_shared_with_terminal_backend() -> None:
    assert Settings(docker_endpoint="unix:///var/run/docker.sock").docker_endpoint
    with pytest.raises(ValueError, match="Only local Unix sockets"):
        Settings(docker_endpoint="tcp://remote.invalid:2376")
