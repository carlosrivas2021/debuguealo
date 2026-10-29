"""Blocking, read-only Docker SDK boundary, run only in a private child process."""

import calendar
import json
import re
import sys
from datetime import datetime

import docker
from docker.errors import APIError, DockerException
from requests.exceptions import RequestException

from debugpilot.core.exceptions import DockerError
from debugpilot.core.models import ContainerInfo
from debugpilot.docker.logs import LogDecoder, read_frames
from debugpilot.docker.probe import PipeError
from debugpilot.storage.config import Settings


def emit(kind: str, **values) -> None:
    print(json.dumps({"kind": kind, **values}, ensure_ascii=True), flush=True)


def bounded_json(api, route: str, **params):
    # SDK transport and status handling, but bound the body before JSON parsing.
    with api._get(api._url(route), params=params, stream=True) as response:
        api._raise_for_status(response)
        body = response.raw.read(8_388_609)
        if len(body) > 8_388_608:
            raise DockerError("Docker metadata exceeds the 8 MiB limit.")
        return json.loads(body)


def run(settings: Settings, request: dict) -> None:
    client = None
    try:
        client = docker.DockerClient(
            base_url=settings.docker_endpoint,
            version="1.41",
            timeout=settings.docker_timeout_seconds,
        )
        client.api.trust_env = False
        api = client.api
        # Set the negotiated daemon API version only after environment discovery
        # is disabled. These small SDK-internal transport helpers preserve stream
        # IDs, unlike SDK logs(), which merges stdout and stderr.
        version = bounded_json(api, "/version")
        api._version = version["ApiVersion"]
        if request["command"] == "containers":
            containers = bounded_json(api, "/containers/json", all=1)
            if not isinstance(containers, list) or len(containers) > 10_000:
                raise DockerError("Container inventory exceeds the supported limit.")
            emit("ready")
            for raw in containers:
                emit("container", value=ContainerInfo.from_docker(raw).model_dump(mode="json"))
        elif request["command"] == "logs":
            container = request["container"]
            if not container or any(
                character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                for character in container
            ):
                raise DockerError("Invalid container name or ID.")
            info = bounded_json(api, f"/containers/{container}/json")
            follow = bool(request["follow"])
            params = {
                "stdout": 1,
                "stderr": 1,
                "timestamps": 1,
                "follow": int(follow),
                "tail": request["tail"],
            }
            if request.get("since") is not None:
                params["since"] = request["since"]
                params["tail"] = "all"  # Replay every record at the inclusive second cursor.
            if request.get("current_run"):
                started = info.get("State", {}).get("StartedAt")
                try:
                    start_time = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    if start_time.tzinfo is None:
                        raise ValueError
                except (AttributeError, TypeError, ValueError):
                    raise DockerError(
                        "Cannot determine this container's current execution."
                    ) from None
                if start_time.year == 1:  # Docker's zero timestamp: never started.
                    emit("ready")
                    return
                # The HTTP API accepts Unix seconds.nanoseconds, unlike the CLI's ISO dates.
                start_second = calendar.timegm(start_time.utctimetuple())
                if request.get("since") is None or request["since"] <= start_second:
                    fraction = re.search(r"\.(\d+)", started)
                    nanos = (fraction[1] if fraction else "").ljust(9, "0")
                    params["since"] = f"{start_second}.{nanos}"
                params["tail"] = "all"
            with api._get(
                api._url(f"/containers/{container}/logs"),
                params=params,
                stream=True,
                timeout=(
                    settings.docker_timeout_seconds,
                    None if follow else settings.docker_timeout_seconds,
                ),
            ) as response:
                api._raise_for_status(response)
                emit("ready")
                decoder = LogDecoder()
                for stream, data in read_frames(
                    response.raw, tty=bool(info.get("Config", {}).get("Tty"))
                ):
                    for entry in decoder.feed(stream, data):
                        emit("log", value=entry.model_dump(mode="json"))
                for entry in decoder.finish():
                    emit("log", value=entry.model_dump(mode="json"))
            if follow:
                current = bounded_json(api, f"/containers/{container}/json")
                if current.get("State", {}).get("Running"):
                    raise DockerError(
                        "Log stream ended while the container is running.", retryable=True
                    )
        else:
            raise DockerError("Unsupported Docker operation.")
    except DockerError as error:
        emit("error", message=str(error), retryable=error.retryable)
    except APIError as error:
        status = error.response.status_code if error.response is not None else 0
        messages = {
            404: "Container not found.",
            401: "Docker access denied.",
            403: "Docker access denied.",
            400: "Docker logging driver does not support this operation.",
            501: "Docker logging driver does not support this operation.",
        }
        emit(
            "error",
            message=messages.get(status, "Docker API operation failed."),
            retryable=status >= 500 and status != 501,
        )
    except (DockerException, RequestException, OSError, PipeError):
        emit(
            "error",
            message="Docker connection failed. Check the local daemon and permissions.",
            retryable=True,
        )
    except (ValueError, KeyError, TypeError, OverflowError):
        emit("error", message="Docker returned invalid or unsupported metadata.", retryable=False)
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    settings = Settings(docker_endpoint=sys.argv[1], docker_timeout_seconds=int(sys.argv[2]))
    run(settings, json.loads(sys.argv[3]))
