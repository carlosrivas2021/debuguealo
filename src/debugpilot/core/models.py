from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


class DiagnosticCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    status: CheckStatus
    detail: str = Field(max_length=1000)


class PortMapping(BaseModel):
    model_config = ConfigDict(frozen=True)
    private_port: int
    public_port: int | None = None
    protocol: str = "tcp"
    host_ip: str | None = None


class ContainerInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(max_length=128)
    name: str = Field(max_length=256)
    image: str = Field(max_length=1024)
    state: str = Field(max_length=64)
    # Docker's human status ("Up 3 hours"); it changes every refresh while running.
    status: str = Field(default="", max_length=256)
    created_at: datetime
    ports: tuple[PortMapping, ...] = ()
    labels: dict[str, str] = Field(default_factory=dict, max_length=1024)
    compose_project: str | None = None
    compose_service: str | None = None

    @classmethod
    def from_docker(cls, value: dict) -> "ContainerInfo":
        labels = value.get("Labels") or {}
        if sum(len(k) + len(v) for k, v in labels.items()) > 32_768:
            raise ValueError("Container labels exceed the metadata limit.")
        identity = value["Id"]
        ports = value.get("Ports")
        if ports is None:
            ports = []
        return cls(
            id=identity,
            name=(value.get("Names") or [identity])[0].removeprefix("/"),
            image=value.get("Image", "unknown"),
            state=value.get("State", "unknown"),
            status=str(value.get("Status") or "")[:256],
            created_at=datetime.fromtimestamp(value.get("Created", 0), UTC),
            labels=labels,
            # Docker lists ports in unstable order; sort so equal inventories compare equal.
            ports=tuple(
                sorted(
                    (
                        PortMapping(
                            private_port=port["PrivatePort"],
                            public_port=port.get("PublicPort"),
                            protocol=port.get("Type", "tcp"),
                            host_ip=port.get("IP"),
                        )
                        for port in ports
                    ),
                    key=lambda port: (
                        port.private_port,
                        port.protocol,
                        port.public_port or 0,
                        port.host_ip or "",
                    ),
                )
            ),
            compose_project=labels.get("com.docker.compose.project"),
            compose_service=labels.get("com.docker.compose.service"),
        )


class StopResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    stopped: tuple[str, ...]
    failed: dict[str, str]


class LogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    timestamp: str | None = Field(default=None, max_length=64)
    stream: Literal["stdout", "stderr", "combined"] = "combined"
    text: str = Field(max_length=16_384)
    severity: Literal["debug", "info", "warning", "error", "critical", "unknown"] = "unknown"
    truncated: bool = False


def _count(value) -> int | None:
    # Docker reports counters as non-negative integers; anything else is "unknown".
    return value if type(value) is int and value >= 0 else None


class ContainerStats(BaseModel):
    """One Docker stats sample; CPU needs two samples, memory is read directly."""

    model_config = ConfigDict(frozen=True)

    cpu_total: int | None = None
    system_cpu: int | None = None
    online_cpus: int | None = None
    memory_usage: int | None = None
    memory_limit: int | None = None

    @classmethod
    def from_docker(cls, value: dict) -> "ContainerStats":
        cpu = value.get("cpu_stats") or {}
        usage = cpu.get("cpu_usage") or {}
        online = _count(cpu.get("online_cpus"))
        if online is None and isinstance(usage.get("percpu_usage"), list):
            online = len(usage["percpu_usage"]) or None
        memory = value.get("memory_stats") or {}
        used = _count(memory.get("usage"))
        details = memory.get("stats") or {}
        # Same as `docker stats`: page cache that can be reclaimed is not "used".
        inactive = _count(details.get("inactive_file", details.get("total_inactive_file")))
        if used is not None and inactive is not None and inactive <= used:
            used -= inactive
        return cls(
            cpu_total=_count(usage.get("total_usage")),
            system_cpu=_count(cpu.get("system_cpu_usage")),
            online_cpus=online,
            memory_usage=used,
            memory_limit=_count(memory.get("limit")),
        )


MAX_MOUNTS = 64
MAX_ENV_NAMES = 256
MAX_HEALTH_OUTPUT = 200


class MountInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: str = Field(max_length=32)
    # A named volume shows its name; a bind mount its host path.
    source: str = Field(default="", max_length=4096)
    destination: str = Field(max_length=4096)
    read_only: bool = False


def _text(value, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


class ContainerRuntime(BaseModel):
    """Runtime facts from one container inspect; environment values are never kept."""

    model_config = ConfigDict(frozen=True)

    health: str | None = Field(default=None, max_length=32)
    health_output: str | None = Field(default=None, max_length=MAX_HEALTH_OUTPUT)
    restart_policy: str | None = Field(default=None, max_length=64)
    restart_count: int | None = None
    exit_code: int | None = None
    oom_killed: bool = False
    mounts: tuple[MountInfo, ...] = Field(default=(), max_length=MAX_MOUNTS)
    env_names: tuple[str, ...] = Field(default=(), max_length=MAX_ENV_NAMES)

    @classmethod
    def from_docker(cls, value: dict) -> "ContainerRuntime":
        state = value.get("State") if isinstance(value.get("State"), dict) else {}
        health = state.get("Health") if isinstance(state.get("Health"), dict) else {}
        log = health.get("Log") if isinstance(health.get("Log"), list) else []
        last = log[-1] if log and isinstance(log[-1], dict) else {}
        output = last.get("Output")
        if not isinstance(output, str) or not output.strip():
            output = None
        else:
            output = output.strip().splitlines()[0]
        host = value.get("HostConfig") if isinstance(value.get("HostConfig"), dict) else {}
        policy = host.get("RestartPolicy") if isinstance(host.get("RestartPolicy"), dict) else {}
        name = _text(policy.get("Name"), 32)
        retries = policy.get("MaximumRetryCount")
        if name == "on-failure" and type(retries) is int and retries > 0:
            name = f"{name}:{retries}"
        mounts = []
        for mount in value.get("Mounts") if isinstance(value.get("Mounts"), list) else []:
            if len(mounts) == MAX_MOUNTS:
                break
            if not isinstance(mount, dict) or not _text(mount.get("Destination"), 4096):
                continue
            mounts.append(MountInfo(
                type=_text(mount.get("Type"), 32) or "unknown",
                source=_text(mount.get("Name"), 4096) or _text(mount.get("Source"), 4096) or "",
                destination=_text(mount.get("Destination"), 4096),
                read_only=mount.get("RW") is False,
            ))
        config = value.get("Config") if isinstance(value.get("Config"), dict) else {}
        env = config.get("Env") if isinstance(config.get("Env"), list) else []
        # Only the names cross this boundary: values often hold secrets.
        names = [item.split("=", 1)[0][:256] for item in env if isinstance(item, str) and item]
        return cls(
            health=_text(health.get("Status"), 32),
            health_output=output[:MAX_HEALTH_OUTPUT] if output else None,
            restart_policy=name[:64] if name else None,
            restart_count=_count(value.get("RestartCount")),
            exit_code=state.get("ExitCode") if type(state.get("ExitCode")) is int else None,
            oom_killed=state.get("OOMKilled") is True,
            mounts=tuple(mounts),
            env_names=tuple(names[:MAX_ENV_NAMES]),
        )


def cpu_percent(previous: ContainerStats | None, current: ContainerStats) -> float | None:
    """CPU use between two samples, where 100 means one full CPU (like `docker stats`)."""
    if previous is None or None in (
        previous.cpu_total, previous.system_cpu, current.cpu_total, current.system_cpu,
        current.online_cpus,
    ):
        return None
    cpu_delta = current.cpu_total - previous.cpu_total
    system_delta = current.system_cpu - previous.system_cpu
    if cpu_delta < 0 or system_delta <= 0:
        return None
    return cpu_delta / system_delta * current.online_cpus * 100
