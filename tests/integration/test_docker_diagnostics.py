import pytest

from debugpilot.core.models import CheckStatus
from debugpilot.docker.diagnostics import DockerDiagnostics
from debugpilot.storage.config import Settings


@pytest.mark.integration
async def test_real_local_docker_probe():
    checks = await DockerDiagnostics(Settings()).inspect()
    docker = checks[0]
    assert "worker failed" not in docker.detail, docker.detail
    if docker.status == CheckStatus.ERROR:
        pytest.skip(docker.detail)
    assert all(check.status == CheckStatus.OK for check in checks)
    assert checks[-1].name == "Docker server"
    assert checks[-1].detail not in {"unknown", "Unavailable", ""}
