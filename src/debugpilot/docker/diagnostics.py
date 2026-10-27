import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from debugpilot.core.models import CheckStatus, DiagnosticCheck
from debugpilot.storage.config import Settings


def default_endpoint() -> str:
    if os.name == "nt":
        return "npipe:////./pipe/docker_engine"
    return "unix:///var/run/docker.sock"


class DockerDiagnostics:
    """Read-only SDK probe with a private environment and cancelable process."""

    def __init__(self, settings: Settings):
        self._endpoint = settings.docker_endpoint or default_endpoint()
        self._timeout = settings.docker_timeout_seconds

    async def inspect(self) -> list[DiagnosticCheck]:
        process = None
        try:
            with tempfile.TemporaryDirectory(prefix="debugpilot-probe-") as directory:
                # SDK construction always reads Docker config. Use an existing
                # private empty config, never the user's registry credentials.
                (Path(directory) / "config.json").write_text("{}", encoding="utf-8")
                environment = {
                    key: value
                    for key, value in os.environ.items()
                    if key.upper() in {"SYSTEMROOT", "WINDIR"}
                }
                environment.update(DOCKER_CONFIG=directory, PYTHONUTF8="1")
                try:
                    async with asyncio.timeout(self._timeout * 2 + 3):
                        process = await asyncio.create_subprocess_exec(
                            sys.executable,
                            "-m",
                            "debugpilot.docker.probe",
                            self._endpoint,
                            str(self._timeout),
                            env=environment,
                            cwd=directory,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL,
                            limit=4096,
                            **({"creationflags": 0x08000000} if os.name == "nt" else {}),
                        )
                        assert process.stdout is not None
                        data = bytearray()
                        while chunk := await process.stdout.read(4097 - len(data)):
                            data.extend(chunk)
                            if len(data) > 4096:
                                raise ValueError("Oversized diagnostic response")
                        await process.wait()
                        if process.returncode != 0:
                            raise ValueError("Diagnostic worker failed")
                        return TypeAdapter(list[DiagnosticCheck]).validate_python(json.loads(data))
                finally:
                    if process is not None:
                        if process.returncode is None:
                            try:
                                process.kill()
                            except ProcessLookupError:
                                pass
                        await process.wait()
        except (OSError, TimeoutError, ValueError, ValidationError):
            return [
                DiagnosticCheck(
                    name="Docker",
                    status=CheckStatus.ERROR,
                    detail="Local diagnostic worker failed or timed out. Check Docker setup.",
                ),
                DiagnosticCheck(
                    name="Permissions", status=CheckStatus.UNKNOWN, detail="Not established"
                ),
                DiagnosticCheck(
                    name="Docker server", status=CheckStatus.UNKNOWN, detail="Unavailable"
                ),
            ]


def endpoint_description(settings: Settings) -> str:
    endpoint = settings.docker_endpoint or default_endpoint()
    if endpoint.startswith("unix://"):
        return f"Local Unix socket: {Path(endpoint.removeprefix('unix://')).name}"
    return "Local Windows named pipe"
