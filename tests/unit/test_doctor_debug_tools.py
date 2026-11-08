"""`debugealo doctor` reports Delve without failing on it; debugpy is bundled."""

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


def doctor(tmp_path):
    return CliRunner().invoke(app, ["doctor", "--config", str(tmp_path / "missing.toml")])


def test_found_delve_is_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(tools.shutil, "which", {"dlv": "/go/bin/dlv"}.get)
    [check] = tools.debug_tool_checks()
    assert check.name == "Delve" and check.status == CheckStatus.OK
    assert "/go/bin/dlv" in check.detail
    result = doctor(tmp_path)
    assert result.exit_code == 0 and "Delve" in result.output


def test_missing_delve_warns_with_install_hint_and_keeps_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(tools.shutil, "which", {}.get)
    [check] = tools.debug_tool_checks()
    assert check.status == CheckStatus.WARNING
    assert "go install github.com/go-delve/delve/cmd/dlv@latest" in check.detail
    result = doctor(tmp_path)
    assert result.exit_code == 0 and "warning" in result.output


def test_doctor_no_longer_checks_debugpy(tmp_path):
    assert "debugpy" not in doctor(tmp_path).output
