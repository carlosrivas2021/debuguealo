"""Self-contained orders demo API and worker; standard library only."""

import json
import os
import sys
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

PROJECT = "orders"


def emit(event, **fields):
    print(json.dumps({"event": event, "project": PROJECT, **fields}), flush=True)


def fetch_json(url):
    # Keep demo traffic direct, independent of host proxy environment variables.
    with build_opener(ProxyHandler({})).open(url, timeout=2) as response:
        return json.load(response)


def make_server(host="0.0.0.0", port=8000, *, marker="initial", upstream_url=None):
    identity = {
        "project": PROJECT,
        "marker": marker,
        "instance": uuid4().hex,
        "started_at": datetime.now(UTC).isoformat(),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                return self.respond(200, identity)
            if self.path != "/flow":
                return self.respond(404, {"error": "not found"})
            result = {"chain": [PROJECT], "hops": [identity]}
            if upstream_url:
                try:
                    downstream = fetch_json(upstream_url.rstrip("/") + "/flow")
                    result["chain"].extend(downstream["chain"])
                    result["hops"].extend(downstream["hops"])
                except (URLError, TimeoutError, ValueError, KeyError, OSError):
                    return self.respond(502, {"error": "upstream unavailable", "chain": [PROJECT]})
            emit("flow", marker=marker, chain=result["chain"])
            return self.respond(200, result)

        def respond(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            emit("request", marker=marker, path=self.path)

    return ThreadingHTTPServer((host, port), Handler)


def poll_once(url, *, marker="initial"):
    result = fetch_json(url)
    emit("worker_poll", marker=marker, chain=result["chain"])
    return result


def main():
    marker = os.environ.get("APP_MARKER", "initial")
    if sys.argv[1:] == ["worker"]:
        url = os.environ.get("API_URL", "http://127.0.0.1:8000/flow")
        while True:
            try:
                poll_once(url, marker=marker)
            except (URLError, TimeoutError, ValueError, KeyError, OSError):
                emit("worker_retry", marker=marker, error="API unavailable")
            time.sleep(5)
    else:
        server = make_server(marker=marker, upstream_url=os.environ.get("UPSTREAM_URL"))
        emit("api_started", marker=marker, port=server.server_port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
