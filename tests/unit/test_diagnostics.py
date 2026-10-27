import asyncio
import json
import subprocess
import sys
from unittest.mock import Mock

import pytest
from docker.errors import DockerException
from pydantic import ValidationError
from typer.testing import CliRunner

from debugpilot.cli import app
from debugpilot.core.models import CheckStatus, DiagnosticCheck
from debugpilot.docker.diagnostics import DockerDiagnostics
from debugpilot.storage.config import Settings


@pytest.mark.parametrize(
    "endpoint",
    [
        "ssh://host",
        "tcp://localhost:2375",
        "npipe:////server/pipe/docker_engine",
        "unix:////server/socket",
    ],
)
def test_remote_endpoints_are_rejected(endpoint):
    with pytest.raises(ValidationError):
        Settings(docker_endpoint=endpoint)


@pytest.mark.parametrize(
    "endpoint", ["unix:///var/run/docker.sock", "npipe:////./pipe/dockerDesktopLinuxEngine"]
)
def test_local_endpoints_are_accepted(endpoint):
    assert Settings(docker_endpoint=endpoint).docker_endpoint == endpoint


def test_diagnostic_worker_closes_sdk_client(monkeypatch):
    from debugpilot.docker.probe import inspect_local

    client = Mock()
    client.version.return_value = {"Version": "test-server"}
    monkeypatch.setattr("debugpilot.docker.probe.docker.DockerClient", Mock(return_value=client))
    checks = inspect_local("unix:///socket", 1)
    assert all(check.status == CheckStatus.OK for check in checks)
    assert checks[-1].detail == "test-server"
    assert client.api.trust_env is False
    client.close.assert_called_once()


def test_worker_failure_is_safe_and_closes_client(monkeypatch):
    from debugpilot.docker.probe import inspect_local

    client = Mock()
    client.ping.side_effect = DockerException("password=secret")
    monkeypatch.setattr("debugpilot.docker.probe.docker.DockerClient", Mock(return_value=client))
    checks = inspect_local("unix:///socket", 1)
    assert checks[0].status == CheckStatus.ERROR
    assert "secret" not in str(checks)
    assert checks[1].status == CheckStatus.UNKNOWN
    client.close.assert_called_once()


@pytest.mark.parametrize("healthy, expected", [(True, 0), (False, 1)])
def test_doctor_exit_codes_and_no_hidden_remote_access(monkeypatch, tmp_path, healthy, expected):
    async def inspect(_self):
        return [DiagnosticCheck(name="Docker", status="ok" if healthy else "error", detail="probe")]

    monkeypatch.setattr(DockerDiagnostics, "inspect", inspect)
    monkeypatch.setenv("DOCKER_HOST", "ssh://must-not-be-contacted")
    result = CliRunner().invoke(app, ["doctor", "--config", str(tmp_path / "missing.toml")])
    assert result.exit_code == expected
    assert "Python" in result.output
    assert "Docker" in result.output
    assert "must-not-be-contacted" not in result.output
    assert not list(tmp_path.iterdir())


async def test_worker_has_private_environment_and_is_reaped_on_cancel(monkeypatch):
    import debugpilot.docker.diagnostics as diagnostics

    started = asyncio.Event()
    captured = {}

    class Output:
        async def read(self, size):
            started.set()
            await asyncio.Event().wait()

    class Process:
        stdout = Output()
        returncode = None
        killed = False
        waited = False

        def kill(self):
            self.killed = True
            self.returncode = -1

        async def wait(self):
            self.waited = True
            return self.returncode

    process = Process()

    async def create(*args, **kwargs):
        captured.update(kwargs)
        assert (
            json.loads(
                (diagnostics.Path(kwargs["env"]["DOCKER_CONFIG"]) / "config.json").read_text()
            )
            == {}
        )
        return process

    monkeypatch.setattr(diagnostics.asyncio, "create_subprocess_exec", create)
    monkeypatch.setenv("DOCKER_HOST", "ssh://private")
    task = asyncio.create_task(DockerDiagnostics(Settings()).inspect())
    await asyncio.wait_for(started.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed and process.waited
    assert "DOCKER_HOST" not in captured["env"]
    assert not diagnostics.Path(captured["env"]["DOCKER_CONFIG"]).exists()


def test_headless_core_import_in_fresh_interpreter():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import debugpilot.core.engine, sys; assert 'textual' not in sys.modules",
        ],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()
