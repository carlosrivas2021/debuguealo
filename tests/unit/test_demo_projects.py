import importlib.util
import json
import threading
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

import pytest

LAB = Path(__file__).parents[2] / "examples" / "multi-project"


def load_project(name):
    spec = importlib.util.spec_from_file_location(f"demo_{name}", LAB / name / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def running(name, *, marker="initial", upstream_url=None):
    module = load_project(name)
    server = module.make_server("127.0.0.1", 0, marker=marker, upstream_url=upstream_url)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02))
    thread.start()
    try:
        yield module, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()


def get(url):
    with build_opener(ProxyHandler({})).open(url, timeout=5) as response:
        return json.load(response)


def test_three_independent_projects_communicate_and_preserve_identity():
    with ExitStack() as stack:
        _, catalog = stack.enter_context(running("catalog", marker="catalog-v1"))
        _, orders = stack.enter_context(running("orders", upstream_url=catalog, marker="orders-v1"))
        _, gateway = stack.enter_context(
            running("gateway", upstream_url=orders, marker="gateway-v1")
        )
        response = get(gateway + "/flow")
        assert response["chain"] == ["gateway", "orders", "catalog"]
        assert [hop["marker"] for hop in response["hops"]] == [
            "gateway-v1",
            "orders-v1",
            "catalog-v1",
        ]
        for name, url in (("gateway", gateway), ("orders", orders), ("catalog", catalog)):
            first = get(url + "/health")
            assert first["project"] == name and first["started_at"] and first["instance"]
            assert get(url + "/health") == first
        assert len({hop["instance"] for hop in response["hops"]}) == 3


@pytest.mark.parametrize("name", ["gateway", "orders", "catalog"])
def test_worker_emits_observable_project_and_marker(name, capsys):
    with running(name, marker="changed") as (module, url):
        result = module.poll_once(url + "/flow", marker="worker-v2")
        assert result["chain"] == [name]
        event = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert event["event"] == "worker_poll"
        assert event["project"] == name and event["marker"] == "worker-v2"
        assert event["chain"] == [name]


def test_upstream_failure_is_bounded_and_reported_without_configuration_leaks():
    with running("gateway", upstream_url="http://127.0.0.1:1") as (_, url):
        with pytest.raises(HTTPError) as caught:
            get(url + "/flow")
        assert caught.value.code == 502
        assert json.load(caught.value) == {"error": "upstream unavailable", "chain": ["gateway"]}
        assert get(url + "/health")["project"] == "gateway"


def test_new_server_instance_changes_without_changing_other_project():
    with running("catalog") as (_, catalog):
        before = get(catalog + "/health")
        with running("orders", marker="v1") as (_, orders):
            first = get(orders + "/health")
        with running("orders", marker="v2") as (_, orders):
            second = get(orders + "/health")
        assert first["instance"] != second["instance"]
        assert first["marker"] == "v1" and second["marker"] == "v2"
        assert get(catalog + "/health") == before
