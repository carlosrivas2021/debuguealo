"""Own and clean up one isolated log fixture; never pull images or touch user containers."""

import json
import sys
import uuid

import docker
from docker.errors import ImageNotFound


def main():
    client = docker.DockerClient(base_url=sys.argv[1], version="1.41", timeout=3)
    client.api.trust_env = False
    container = None
    try:
        client.api._version = client.version()["ApiVersion"]
        image = None
        for name in ("redis:7-alpine", "postgres:15-alpine", "alpine:3.20", "python:3.12-slim"):
            try:
                image = client.images.get(name)
                break
            except ImageNotFound:
                pass
        if image is None:
            print(
                json.dumps({"skip": "No cached supported fixture image; no pull attempted."}),
                flush=True,
            )
            return
        marker = "debugpilot-test-" + uuid.uuid4().hex
        script = (
            "printf 'INFO debugpilot-start\\n'; "
            "printf 'ERROR debugpilot-stderr\\n' >&2; "
            "sleep 1; printf 'INFO debugpilot-later\\n'; sleep 60"
        )
        container = client.containers.create(
            image.id,
            command=["sh", "-c", script],
            entrypoint="",
            name=marker,
            labels={"debugpilot-test": marker},
            network_mode="none",
            read_only=True,
            mem_limit="32m",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
        )
        container.start()
        print(json.dumps({"id": container.id}), flush=True)
        sys.stdin.readline()  # EOF also tears down this fixture.
    finally:
        if container is not None:
            container.remove(force=True)
        client.close()


if __name__ == "__main__":
    main()
