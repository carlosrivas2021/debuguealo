import json

import pytest

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.exception_modes import ExceptionModeStore


def test_round_trip_keeps_non_default_modes_only(tmp_path):
    store = ExceptionModeStore(tmp_path / "projects" / "exceptions.json")
    assert store.load() == {}
    first, second, third = (tmp_path / name for name in ("a", "b", "c"))
    store.save({first: "all", second: "none", third: "uncaught"})
    assert store.load() == {first.resolve(): "all", second.resolve(): "none"}
    document = json.loads(store.path.read_text())
    assert document == {"version": 1, "modes": [
        {"root": str(first.resolve()), "mode": "all"},
        {"root": str(second.resolve()), "mode": "none"},
    ]}


def test_default_location_is_beside_the_other_project_files(tmp_path):
    store = ExceptionModeStore()
    store.save({tmp_path / "app": "all"})
    assert store.path == tmp_path / ".debugpilot" / "projects" / "exceptions.json"


def test_unknown_mode_is_refused_and_the_file_is_kept(tmp_path):
    store = ExceptionModeStore(tmp_path / "exceptions.json")
    store.save({tmp_path / "app": "all"})
    before = store.path.read_bytes()
    with pytest.raises(ConfigurationError, match="Cannot save exception settings"):
        store.save({tmp_path / "app": "sometimes"})
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("content", [
    "not json",
    '{"version": 2, "modes": []}',
    '{"version": 1, "modes": [{"root": "relative", "mode": "all"}]}',
    '{"version": 1, "modes": [{"root": "/app", "mode": "sometimes"}]}',
    '{"version": 1, "modes": [{"root": "/app", "mode": "all"}, {"root": "/app", "mode": "none"}]}',
])
def test_invalid_file_is_reported_and_never_replaced(tmp_path, content):
    store = ExceptionModeStore(tmp_path / "exceptions.json")
    store.path.write_text(content)
    with pytest.raises(ConfigurationError, match="Invalid exception settings"):
        store.load()
    with pytest.raises(ConfigurationError, match="Invalid exception settings"):
        store.save({tmp_path / "app": "all"})
    assert store.path.read_text() == content
