"""`debugealo doctor` reports the optional debugging tools without failing on them."""

import subprocess

import pytest
from typer.testing import CliRunner

from debugpilot.cli import app
from debugpilot.core.models import CheckStatus, DiagnosticCheck
from debugpilot.debugger import tools
from debugpilot.docker.diagnostics import DockerDiagnostics


@pytest.fixture(autouse=True)
def healthy_docker(monkeypatch):
    async def inspect(_self):
        return [DiagnosticCheck(name="Docker", status="ok", detail="probe")]

    monkeypatch.setattr(DockerDiagnostics, "inspect", inspect)


def fake_which(found):
    return lambda name: found.get(name)


def doctor(tmp_path):
    return CliRunner().invoke(app, ["doctor", "--config", str(tmp_path / "missing.toml")])


def checks_by_name():
    return {check.name: check for check in tools.debug_tool_checks()}


def test_found_tools_are_ok_and_name_the_checked_interpreter(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tools.shutil, "which", fake_which({"dlv": "/go/bin/dlv", "python3": "/usr/bin/python3"})
    )
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(tools.subprocess, "run", run)
    checks = checks_by_name()
    assert checks["Delve"].status == CheckStatus.OK and "/go/bin/dlv" in checks["Delve"].detail
    assert checks["debugpy"].status == CheckStatus.OK
    assert "/usr/bin/python3" in checks["debugpy"].detail
    assert "own interpreter" in checks["debugpy"].detail
    assert calls[0][0] == "/usr/bin/python3"
    result = doctor(tmp_path)
    assert result.exit_code == 0 and "Delve" in result.output and "debugpy" in result.output


def test_missing_tools_warn_with_install_hints_and_keep_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(tools.shutil, "which", fake_which({"python3": "/usr/bin/python3"}))
    monkeypatch.setattr(
        tools.subprocess, "run", lambda argv, **_: subprocess.CompletedProcess(argv, 1)
    )
    checks = checks_by_name()
    assert checks["Delve"].status == CheckStatus.WARNING
    assert "go install github.com/go-delve/delve/cmd/dlv@latest" in checks["Delve"].detail
    assert checks["debugpy"].status == CheckStatus.WARNING
    assert "/usr/bin/python3 -m pip install debugpy" in checks["debugpy"].detail
    result = doctor(tmp_path)
    assert result.exit_code == 0 and "warning" in result.output


def test_unreachable_interpreter_check_is_unknown(monkeypatch):
    monkeypatch.setattr(tools.shutil, "which", fake_which({"python3": "/usr/bin/python3"}))

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 5))

    monkeypatch.setattr(tools.subprocess, "run", timeout)
    assert checks_by_name()["debugpy"].status == CheckStatus.UNKNOWN


def test_no_python_on_path_warns(monkeypatch):
    monkeypatch.setattr(tools.shutil, "which", fake_which({}))
    check = checks_by_name()["debugpy"]
    assert check.status == CheckStatus.WARNING and "interpreter" in check.detail
