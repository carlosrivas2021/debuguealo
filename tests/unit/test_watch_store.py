import json

import pytest

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.watches import WatchStore


def _root(tmp_path, name="project"):
    root = tmp_path / name
    root.mkdir()
    return root.resolve()


def test_absent_store_is_empty_and_creates_nothing(tmp_path):
    store = WatchStore(tmp_path / "watches.json")
    assert store.load() == {}
    assert not store.path.exists()


def test_round_trip_keeps_order_and_canonical_roots(tmp_path):
    store = WatchStore(tmp_path / "watches.json")
    one, two = _root(tmp_path, "one"), _root(tmp_path, "two")
    store.save({one: ["total", "len(items) > 2"], two: ["user.id"], tmp_path / "empty": []})
    assert store.load() == {one: ("total", "len(items) > 2"), two: ("user.id",)}
    document = json.loads(store.path.read_text())
    assert document == {"version": 1, "watches": [
        {"root": str(one), "expressions": ["total", "len(items) > 2"]},
        {"root": str(two), "expressions": ["user.id"]}]}


@pytest.mark.parametrize("entries", [
    [{"root": "relative", "expressions": ["x"]}],
    [{"root": "{root}", "expressions": []}],
    [{"root": "{root}", "expressions": [" "]}],
    [{"root": "{root}", "expressions": ["a\u0000b"]}],
    [{"root": "{root}", "expressions": ["x" * 1001]}],
    [{"root": "{root}", "expressions": ["x"] * 101}],
    [{"root": "{root}", "expressions": "x"}],
    [{"root": "{root}", "expressions": ["x"], "extra": 1}],
    [{"root": "{root}", "expressions": ["x"]}, {"root": "{root}", "expressions": ["y"]}],
], ids=["relative-root", "empty-list", "blank", "nul", "too-long", "too-many", "not-a-list",
        "unknown-key", "duplicate-root"])
def test_invalid_files_are_rejected_and_kept(tmp_path, entries):
    root = _root(tmp_path)
    path = tmp_path / "watches.json"
    text = json.dumps({"version": 1, "watches": entries}).replace("{root}", str(root))
    path.write_text(text)
    before = path.read_bytes()
    store = WatchStore(path)
    with pytest.raises(ConfigurationError, match="Invalid watch expressions"):
        store.load()
    with pytest.raises(ConfigurationError, match="Invalid watch expressions"):
        store.save({})
    assert path.read_bytes() == before


def test_save_rejects_invalid_expressions_without_publishing(tmp_path):
    store = WatchStore(tmp_path / "watches.json")
    root = _root(tmp_path)
    store.save({root: ["kept"]})
    before = store.path.read_bytes()
    with pytest.raises(ConfigurationError, match="Cannot save watch expressions"):
        store.save({root: ["x" * 1001]})
    assert store.path.read_bytes() == before
