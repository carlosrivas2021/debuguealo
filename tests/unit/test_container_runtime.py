"""Health, restart policy, exit code, mounts and env names from one container inspect."""

import json
import os

import pytest
from test_docker_inventory_worker import spawns, unreachable  # noqa: F401

from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import ContainerRuntime, MountInfo
from debugpilot.docker.service import DockerService

INSPECT = {
    "State": {
        "Status": "running", "ExitCode": 0, "OOMKilled": False,
        "Health": {"Status": "unhealthy", "FailingStreak": 3, "Log": [
            {"ExitCode": 0, "Output": "ok\n"},
            {"ExitCode": 1, "Output": "curl: (7) Failed to connect\nsecond line"},
        ]},
    },
    "RestartCount": 2,
    "HostConfig": {"RestartPolicy": {"Name": "on-failure", "MaximumRetryCount": 5}},
    "Mounts": [
        {"Type": "bind", "Source": "/home/me/app", "Destination": "/app", "RW": True},
        {"Type": "volume", "Name": "pgdata", "Source": "/var/lib/docker/volumes/pgdata/_data",
         "Destination": "/var/lib/postgresql/data", "RW": False},
    ],
    "Config": {"Env": ["PATH=/usr/bin", "DATABASE_PASSWORD=hunter2", "EMPTY=", "NOVALUE"]},
}


def test_inspect_keeps_health_restarts_mounts_and_only_env_names():
    runtime = ContainerRuntime.from_docker(INSPECT)
    assert runtime.health == "unhealthy"
    assert runtime.health_output == "curl: (7) Failed to connect"
    assert runtime.restart_policy == "on-failure:5"
    assert runtime.restart_count == 2
    assert runtime.exit_code == 0 and runtime.oom_killed is False
    assert runtime.mounts == (
        MountInfo(type="bind", source="/home/me/app", destination="/app", read_only=False),
        MountInfo(type="volume", source="pgdata", destination="/var/lib/postgresql/data",
                  read_only=True),
    )
    assert runtime.env_names == ("PATH", "DATABASE_PASSWORD", "EMPTY", "NOVALUE")
    dumped = json.dumps(runtime.model_dump(mode="json"))
    assert "hunter2" not in dumped and "/usr/bin" not in dumped


def test_inspect_without_health_or_policy_and_with_malformed_values():
    runtime = ContainerRuntime.from_docker({
        "State": {"ExitCode": 137, "OOMKilled": True, "Health": "bad"},
        "RestartCount": -1,
        "HostConfig": {"RestartPolicy": {"Name": "always", "MaximumRetryCount": 0}},
        "Mounts": [{"Type": "tmpfs", "Destination": "/tmp"}, "bad", {"Destination": 3}],
        "Config": {"Env": None},
    })
    assert runtime.health is None and runtime.health_output is None
    assert runtime.restart_policy == "always"
    assert runtime.restart_count is None
    assert runtime.exit_code == 137 and runtime.oom_killed is True
    assert runtime.mounts == (
        MountInfo(type="tmpfs", source="", destination="/tmp", read_only=False),)
    assert runtime.env_names == ()
    assert ContainerRuntime.from_docker({}) == ContainerRuntime()


def test_inspect_bounds_mounts_env_names_and_text():
    runtime = ContainerRuntime.from_docker({
        "Mounts": [{"Type": "bind", "Source": f"/s{n}", "Destination": f"/d{n}"}
                   for n in range(100)],
        "Config": {"Env": [f"V{n}=x" for n in range(500)]},
        "State": {"Health": {"Status": "healthy", "Log": [{"Output": "y" * 5000}]}},
    })
    assert len(runtime.mounts) == 64
    assert len(runtime.env_names) == 256
    assert len(runtime.health_output) == 200


@pytest.mark.skipif(os.name == "nt", reason="uses a local Unix socket endpoint")
async def test_runtime_reuses_the_persistent_inventory_worker(tmp_path, spawns):  # noqa: F811
    service = DockerService(unreachable(tmp_path))
    try:
        for _ in range(2):
            with pytest.raises(DockerError, match="Docker connection failed"):
                await service.container_runtime("web")
            with pytest.raises(DockerError, match="Docker connection failed"):
                await service.list_containers()
        assert len(spawns) == 1
    finally:
        await service.close()


async def test_runtime_rejects_invalid_container_names(tmp_path):
    service = DockerService(unreachable(tmp_path))
    with pytest.raises(ValueError, match="Invalid container"):
        await service.container_runtime("bad name;")
    assert service._inventory is None


def test_an_absurd_retry_count_is_trimmed_instead_of_failing_the_inspect():
    runtime = ContainerRuntime.from_docker({
        "HostConfig": {"RestartPolicy": {"Name": "on-failure", "MaximumRetryCount": 10**80}},
        "RestartCount": 1,
    })
    assert runtime.restart_policy.startswith("on-failure:1000")
    assert len(runtime.restart_policy) == 64 and runtime.restart_count == 1
