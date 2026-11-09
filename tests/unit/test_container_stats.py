import os

import pytest
from test_docker_inventory_worker import spawns, unreachable  # noqa: F401

from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import ContainerStats, cpu_percent
from debugpilot.docker.service import DockerService

# Shapes from Docker's /containers/{id}/stats?stream=0&one-shot=1 (precpu is empty).
CGROUP_V2 = {
    "cpu_stats": {"cpu_usage": {"total_usage": 5_000_000}, "system_cpu_usage": 90_000_000,
                  "online_cpus": 4},
    "precpu_stats": {"cpu_usage": {"total_usage": 0}, "throttling_data": {}},
    "memory_stats": {"usage": 52_428_800, "limit": 1_073_741_824,
                     "stats": {"inactive_file": 2_097_152, "anon": 40_000_000}},
}
CGROUP_V1 = {
    "cpu_stats": {"cpu_usage": {"total_usage": 7, "percpu_usage": [3, 4]},
                  "system_cpu_usage": 100},
    "memory_stats": {"usage": 3_000, "limit": 10_000, "stats": {"total_inactive_file": 1_000}},
}
STOPPED = {"read": "0001-01-01T00:00:00Z", "cpu_stats": {"cpu_usage": {"total_usage": 0},
           "throttling_data": {}}, "memory_stats": {}}


def test_sample_from_cgroup_v2_subtracts_inactive_file():
    stats = ContainerStats.from_docker(CGROUP_V2)
    assert stats == ContainerStats(cpu_total=5_000_000, system_cpu=90_000_000, online_cpus=4,
                                   memory_usage=50_331_648, memory_limit=1_073_741_824)


def test_sample_from_cgroup_v1_counts_cpus_and_uses_total_inactive_file():
    stats = ContainerStats.from_docker(CGROUP_V1)
    assert (stats.online_cpus, stats.memory_usage, stats.memory_limit) == (2, 2_000, 10_000)


def test_stopped_container_sample_has_no_values():
    stats = ContainerStats.from_docker(STOPPED)
    assert (stats.system_cpu, stats.memory_usage, stats.memory_limit) == (None, None, None)


def test_cpu_percent_uses_two_consecutive_samples():
    previous = ContainerStats(cpu_total=1_000, system_cpu=10_000, online_cpus=2)
    current = ContainerStats(cpu_total=1_200, system_cpu=11_000, online_cpus=2)
    assert cpu_percent(previous, current) == pytest.approx(40.0)
    assert cpu_percent(None, current) is None
    # No progress, a restarted counter, or a stopped sample give no percentage.
    assert cpu_percent(current, current) is None
    assert cpu_percent(current, previous) is None
    assert cpu_percent(previous, ContainerStats()) is None


@pytest.mark.skipif(os.name == "nt", reason="uses a local Unix socket endpoint")
async def test_stats_reuse_the_persistent_inventory_worker(tmp_path, spawns):  # noqa: F811
    service = DockerService(unreachable(tmp_path))
    try:
        for _ in range(2):
            with pytest.raises(DockerError, match="Docker connection failed"):
                await service.container_stats("web")
            with pytest.raises(DockerError, match="Docker connection failed"):
                await service.list_containers()
        assert len(spawns) == 1
    finally:
        await service.close()


async def test_stats_rejects_invalid_container_names(tmp_path):
    service = DockerService(unreachable(tmp_path))
    with pytest.raises(ValueError, match="Invalid container"):
        await service.container_stats("bad name;")
    assert service._inventory is None
