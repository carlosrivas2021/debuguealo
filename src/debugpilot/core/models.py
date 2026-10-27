from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CheckStatus(StrEnum):
    OK = "ok"
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
        return cls(
            id=identity,
            name=(value.get("Names") or [identity])[0].removeprefix("/"),
            image=value.get("Image", "unknown"),
            state=value.get("State", "unknown"),
            created_at=datetime.fromtimestamp(value.get("Created", 0), UTC),
            labels=labels,
            ports=tuple(
                PortMapping(
                    private_port=port["PrivatePort"],
                    public_port=port.get("PublicPort"),
                    protocol=port.get("Type", "tcp"),
                    host_ip=port.get("IP"),
                )
                for port in value.get("Ports", [])
            ),
            compose_project=labels.get("com.docker.compose.project"),
            compose_service=labels.get("com.docker.compose.service"),
        )


class LogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    timestamp: str | None = Field(default=None, max_length=64)
    stream: Literal["stdout", "stderr", "combined"] = "combined"
    text: str = Field(max_length=16_384)
    severity: Literal["debug", "info", "warning", "error", "critical", "unknown"] = "unknown"
    truncated: bool = False
