import json
import sys

import docker
from docker.errors import APIError, DockerException
from requests.exceptions import RequestException

from debugpilot.core.models import CheckStatus, DiagnosticCheck

if sys.platform == "win32":
    from pywintypes import error as PipeError
else:
    PipeError = OSError


def inspect_local(endpoint: str, timeout: int) -> list[DiagnosticCheck]:
    """Blocking probe; run only in an isolated, short-lived worker process."""
    client = None
    try:
        # Use a fixed API version for construction so failed negotiation still
        # leaves a client we can close; /version and /_ping need no negotiation.
        client = docker.DockerClient(base_url=endpoint, version="1.41", timeout=timeout)
        client.api.trust_env = False
        if not client.ping():
            raise DockerException("Ping failed")
        version = str(client.version().get("Version", "unknown"))[:80]
        return [
            DiagnosticCheck(name="Docker", status=CheckStatus.OK, detail="Local daemon reachable"),
            DiagnosticCheck(
                name="Permissions", status=CheckStatus.OK, detail="Read API accessible"
            ),
            DiagnosticCheck(name="Docker server", status=CheckStatus.OK, detail=version),
        ]
    except (DockerException, RequestException, OSError, PipeError) as error:
        denied = (
            isinstance(error, PermissionError)
            or (
                isinstance(error, APIError)
                and error.response is not None
                and error.response.status_code in {401, 403}
            )
            or getattr(error, "winerror", None) == 5
        )
        return [
            DiagnosticCheck(
                name="Docker",
                status=CheckStatus.ERROR,
                detail=(
                    "Access denied. Check Docker socket permissions."
                    if denied
                    else "Local daemon unavailable. Start Docker and check the endpoint."
                ),
            ),
            DiagnosticCheck(
                name="Permissions",
                status=CheckStatus.ERROR if denied else CheckStatus.UNKNOWN,
                detail="Access denied" if denied else "Not established; Docker is unreachable",
            ),
            DiagnosticCheck(name="Docker server", status=CheckStatus.UNKNOWN, detail="Unavailable"),
        ]
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    from debugpilot.storage.config import Settings

    settings = Settings(docker_endpoint=sys.argv[1], docker_timeout_seconds=int(sys.argv[2]))
    checks = inspect_local(settings.docker_endpoint, settings.docker_timeout_seconds)
    print(json.dumps([check.model_dump(mode="json") for check in checks]))
