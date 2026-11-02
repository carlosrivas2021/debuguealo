import subprocess

import debugpilot.tui.clipboard as clipboard


def test_copy_native_pipes_text_to_platform_tool(monkeypatch):
    calls = []
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: f"/usr/bin/{name}")

    def run(command, **kwargs):
        calls.append((command, kwargs["input"], kwargs["shell"]))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(clipboard.subprocess, "run", run)
    assert clipboard.copy_native("Published ports: 0.0.0.0:41165->8080/tcp ñ") is True
    assert calls == [
        (["/usr/bin/pbcopy"], "Published ports: 0.0.0.0:41165->8080/tcp ñ".encode(), False)
    ]


def test_copy_native_skips_over_ssh_and_survives_tool_failures(monkeypatch):
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("SSH_TTY", "/dev/ttys001")
    assert clipboard.copy_native("x") is False

    monkeypatch.delenv("SSH_TTY")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    def boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("pbcopy", 2)

    monkeypatch.setattr(clipboard.subprocess, "run", boom)
    assert clipboard.copy_native("x") is False


def test_copy_native_returns_false_without_a_tool(monkeypatch):
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setattr(clipboard.shutil, "which", lambda _name: None)
    assert clipboard.copy_native("x") is False
