"""Execution-boundary checks using fake processes, never Docker or Bash."""

import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import debugpilot.terminal.session as backend
from debugpilot.core.models import ContainerInfo
from debugpilot.terminal import TerminalSession, TerminalUnavailable


@pytest.fixture
def adapters(monkeypatch, tmp_path):
    calls = []
    control = {"windows": False, "failure": None}
    temp_root = tmp_path / "session-temp"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))
    monkeypatch.setattr(backend, "_windows_platform", lambda: control["windows"], raising=False)
    monkeypatch.setattr(backend.shutil, "which", lambda name: str(tmp_path / name))

    class Process:
        def poll(self):
            return 0

        def wait(self):
            return 0

        def read(self, size):
            raise EOFError

        def close(self, *, force):
            pass

    def capture(kind, argv, kwargs):
        calls.append((kind, list(argv), kwargs))
        if control["failure"] is not None:
            raise control["failure"]
        return Process()

    # Exercise the POSIX adapter without importing platform-only modules or
    # opening a real terminal. A pipe gives it portable, owned descriptors;
    # closing the simulated slave also delivers EOF to the reader.
    monkeypatch.setitem(sys.modules, "pty", SimpleNamespace(openpty=os.pipe))
    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(ioctl=lambda *_args: None))
    monkeypatch.setitem(sys.modules, "termios", SimpleNamespace(TIOCSWINSZ=0))
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: capture("posix", argv, kw))
    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(
            PtyProcess=SimpleNamespace(spawn=lambda argv, **kw: capture("conpty", argv, kw))
        ),
    )
    return control, calls, temp_root


@pytest.fixture
def inherited(monkeypatch, tmp_path):
    user_config = tmp_path / "user-docker"
    user_config.mkdir()
    contents = b'{"currentContext":"untrusted","auths":{"fixture":"not-a-secret"}}'
    config_file = user_config / "config.json"
    config_file.write_bytes(contents)
    values = {
        "DOCKER_HOST": "tcp://untrusted.invalid:2376",
        "DOCKER_CONTEXT": "untrusted",
        "DOCKER_CONFIG": str(user_config),
        "DOCKER_TLS": "1",
        "DOCKER_TLS_VERIFY": "1",
        "DOCKER_CERT_PATH": "untrusted-certificates",
        "DOCKER_API_VERSION": "untrusted-api",
        "DOCKER_CUSTOM_HEADERS": "untrusted-header",
        "docker_context": "untrusted-case-variant",
        "TERMINAL_KEEP_ME": "preserved",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    # Windows normalizes environment names, so the two context spellings
    # cannot retain distinct values. Snapshot what was actually installed.
    return {key: os.environ[key] for key in values}, config_file, contents


def assert_dedicated_config(config: Path, temp_root: Path, inherited_directory: str):
    """Snapshot the local fixture before yielding to EOF, which can remove it."""
    assert config.is_dir() and config.parent == temp_root
    assert list(config.iterdir()) == []
    assert str(config) != inherited_directory
    if os.name == "posix":
        assert config.stat().st_mode & 0o077 == 0


def assert_config_removed(config: Path):
    assert not config.exists()
    assert list(config.parent.iterdir()) == []


def running_container():
    return ContainerInfo(
        id="a" * 64,
        name="fixture",
        image="fixture",
        state="running",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("windows", [False, True], ids=["posix", "conpty"])
async def test_container_exec_has_dedicated_config_and_sanitized_env(
    adapters, inherited, tmp_path, windows
):
    control, calls, temp_root = adapters
    control["windows"] = windows
    values, user_config, original = inherited
    endpoint = "npipe:////./pipe/docker_engine" if windows else "unix:///var/run/docker.sock"
    session = TerminalSession(lambda text: None)
    try:
        await session.open_container(running_container(), endpoint, tmp_path)
        kind, argv, kwargs = calls[0]
        assert kind == ("conpty" if windows else "posix")
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert {key for key in env if key.upper().startswith("DOCKER_")} == {"DOCKER_CONFIG"}
        config = Path(env["DOCKER_CONFIG"])
        assert_dedicated_config(config, temp_root, values["DOCKER_CONFIG"])
        assert env["TERMINAL_KEEP_ME"] == "preserved"
        expected = [
            str(tmp_path / "docker"),
            "--host",
            endpoint,
            "exec",
            "-it",
            "a" * 64,
            "/bin/sh",
        ]
        assert argv[-len(expected) :] == expected
        assert str(kwargs["cwd"]) == str(tmp_path)
        assert kwargs.get("dimensions", (24, 80)) == (24, 80)
    finally:
        await session.close_session()
    assert_config_removed(config)
    assert list(temp_root.iterdir()) == []
    assert all(os.environ[key] == value for key, value in values.items())
    assert user_config.read_bytes() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("windows", [False, True], ids=["posix", "conpty"])
async def test_host_environment_is_not_replaced_by_container_isolation(
    adapters, inherited, tmp_path, windows
):
    control, calls, temp_root = adapters
    control["windows"] = windows
    session = TerminalSession(lambda text: None)
    try:
        await session.open_host(tmp_path)
        kind, argv, kwargs = calls[0]
        assert kind == ("conpty" if windows else "posix")
        assert kwargs["env"] is None
        assert argv[-4:] == [
            str(tmp_path / ("bash.exe" if windows else "bash")),
            "--noprofile",
            "--norc",
            "-i",
        ]
        assert list(temp_root.iterdir()) == []
    finally:
        await session.close_session()
    values, config, original = inherited
    assert all(os.environ[key] == value for key, value in values.items())
    assert config.read_bytes() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True], ids=["failure", "cancel"])
async def test_failed_spawn_removes_config_without_mutating_user_state(
    adapters, inherited, tmp_path, cancelled
):
    control, calls, temp_root = adapters
    control["windows"] = cancelled
    control["failure"] = asyncio.CancelledError() if cancelled else OSError("fixture spawn failure")
    session = TerminalSession(lambda text: None)
    expected = asyncio.CancelledError if cancelled else TerminalUnavailable
    with pytest.raises(expected):
        await session.open_container(running_container(), "unix:///var/run/docker.sock", tmp_path)
    env = calls[0][2]["env"]
    assert isinstance(env, dict) and "DOCKER_CONFIG" in env
    assert_config_removed(Path(env["DOCKER_CONFIG"]))
    assert list(temp_root.iterdir()) == []
    values, config, original = inherited
    assert all(os.environ[key] == value for key, value in values.items())
    assert config.read_bytes() == original
    await session.close_session()


@pytest.mark.asyncio
@pytest.mark.parametrize("windows", [False, True], ids=["posix", "conpty"])
async def test_eof_releases_docker_config_once(adapters, tmp_path, windows):
    control, calls, temp_root = adapters
    control["windows"] = windows
    exits = []
    ended = asyncio.Event()

    def on_exit():
        exits.append("exited")
        ended.set()

    session = TerminalSession(on_output=lambda text: None, on_exit=on_exit)
    try:
        await session.open_container(running_container(), "unix:///var/run/docker.sock", tmp_path)
        config = Path(calls[0][2]["env"]["DOCKER_CONFIG"])
        await asyncio.wait_for(ended.wait(), timeout=2)
        assert_config_removed(config)
        await session.close_session()
        await session.close_session()
        assert exits == ["exited"]
        assert list(temp_root.iterdir()) == []
    finally:
        await session.close_session()


@pytest.mark.asyncio
async def test_explicit_alternative_local_pipe_remains_valid(adapters, tmp_path):
    control, calls, temp_root = adapters
    control["windows"] = True
    endpoint = "npipe:////./pipe/docker_engineX"
    session = TerminalSession(lambda text: None)
    try:
        await session.open_container(running_container(), endpoint, tmp_path)
        assert calls[0][0] == "conpty"
        assert calls[0][1][1:3] == ["--host", endpoint]
    finally:
        await session.close_session()
    assert list(temp_root.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["tcp://remote.invalid:2376", ""])
async def test_rejected_target_does_not_spawn_or_create_config(
    adapters, inherited, tmp_path, endpoint
):
    _, calls, temp_root = adapters
    session = TerminalSession(lambda text: None)
    with pytest.raises(TerminalUnavailable):
        await session.open_container(running_container(), endpoint, tmp_path)
    assert calls == []
    assert list(temp_root.iterdir()) == []
    values, config, original = inherited
    assert all(os.environ[key] == value for key, value in values.items())
    assert config.read_bytes() == original
    await session.close_session()
