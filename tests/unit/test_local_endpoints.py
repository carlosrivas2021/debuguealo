import pytest
from pydantic import ValidationError

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
