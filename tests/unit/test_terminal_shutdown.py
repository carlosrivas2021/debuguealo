"""Portable POSIX-adapter proofs; these do not establish native WSL behavior."""

import asyncio
import json
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import debugpilot.terminal.session as terminal
from debugpilot.core.models import ContainerInfo
from debugpilot.terminal.code_session import CodeSession
from debugpilot.terminal.session import TerminalSession


@pytest.fixture
def posix_adapter(monkeypatch):
    sleeping = asyncio.Event()
    resume = asyncio.Event()
    waiting = asyncio.Event()
    release = asyncio.Event()
    closed = []
    signals = []
    reads = []
    chunks = iter((b"hello ", b"\xc3", b"\xa9", b""))
    state = SimpleNamespace(race=False, argv=None, exited=False)

    class Process:
        pid = 12345

        def poll(self):
            return 0 if state.exited else None

        def wait(self):
            state.exited = True
            return 0

    process = Process()

    def killpg(pid, sig):
        signals.append((pid, sig))
        if sig == 0 and state.exited:
            raise ProcessLookupError

    def open_adapter(self, argv, cwd, dimensions, env):
        state.argv = argv
        self.process = process
        self._fd = -12345
        if isinstance(self, CodeSession):
            # Emulate the worker's public exit-status protocol, not its execution.
            Path(argv[2]).write_text(json.dumps({"exit_code": 0}), encoding="utf-8")

    async def sleep(_delay):
        if state.race:
            sleeping.set()
            await resume.wait()
        else:
            await asyncio.sleep(0)

    async def to_thread(func, *args):
        if state.race and func == process.wait:
            waiting.set()
            await release.wait()
            return process.wait()
        return await asyncio.to_thread(func, *args)

    def read(fd, size):
        reads.append(fd)
        if fd is None:
            raise TypeError("'NoneType' object cannot be interpreted as an integer")
        assert fd == -12345 and size == terminal.MAX_READ
        return next(chunks)

    monkeypatch.setattr(terminal, "_windows_platform", lambda: False)
    monkeypatch.setattr(terminal.shutil, "which", lambda _name: sys.executable)
    monkeypatch.setattr(TerminalSession, "_open_posix", open_adapter)
    monkeypatch.setattr(terminal, "asyncio", SimpleNamespace(**(vars(asyncio) | {
        "sleep": sleep, "to_thread": to_thread,
    })))
    monkeypatch.setattr(terminal, "os", SimpleNamespace(**(vars(terminal.os) | {
        "read": read, "close": closed.append, "killpg": killpg,
    })))
    return SimpleNamespace(
        state=state, sleeping=sleeping, resume=resume, waiting=waiting, release=release,
        closed=closed, signals=signals, reads=reads,
    )


async def open_public(session, kind, cwd):
    if kind == "host":
        await session.open_host(cwd)
    elif kind == "container":
        container = ContainerInfo(
            id="a" * 64, name="sample", image="example", state="running",
            created_at=datetime.now(UTC),
        )
        await session.open_container(container, "unix:///var/run/docker.sock", cwd)
    else:
        await session.open_command((sys.executable, "-c", "print('hello é')"), cwd)


@pytest.mark.asyncio
async def test_close_while_posix_reader_sleeps(posix_adapter, tmp_path):
    adapter = posix_adapter
    adapter.state.race = True
    output, exits = [], []
    session = TerminalSession(output.append, lambda: exits.append("exit"))
    await session.open_host(tmp_path)
    await asyncio.wait_for(adapter.sleeping.wait(), 2)
    reader_done = asyncio.Event()
    session._reader.add_done_callback(lambda _task: reader_done.set())
    closing = asyncio.create_task(session.close_session())
    try:
        await asyncio.wait_for(adapter.waiting.wait(), 2)
        assert adapter.closed == [-12345]
        adapter.resume.set()
        await asyncio.wait_for(reader_done.wait(), 2)
        adapter.release.set()
        await asyncio.wait_for(closing, 2)
        await session.close_session()
        assert output == []
        assert exits == ["exit"]
        assert adapter.reads == []
        assert adapter.closed == [-12345]
        assert adapter.signals == [(12345, signal.SIGTERM), (12345, 0)]
        assert session.process is None and session._fd is None and session._reader is None
    finally:
        adapter.resume.set()
        adapter.release.set()
        await asyncio.gather(closing, return_exceptions=True)
        await session.close_session()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["host", "container", "code"])
async def test_normal_utf8_output_exit_and_repeated_close(posix_adapter, tmp_path, kind):
    output, exits = [], []
    exited = asyncio.Event()

    def on_exit():
        exits.append("exit")
        exited.set()

    session = (CodeSession if kind == "code" else TerminalSession)(output.append, on_exit)
    try:
        await open_public(session, kind, tmp_path)
        await asyncio.wait_for(exited.wait(), 2)
        await session.close_session()
        await session.close_session()
        assert output == ["hello ", "é"]
        assert exits == ["exit"]
        assert posix_adapter.closed == [-12345]
        assert posix_adapter.signals == []
        assert session.process is None and session._fd is None and session._reader is None
        if kind == "code":
            assert session.exit_code == 0 and session.error is None
    finally:
        await session.close_session()
