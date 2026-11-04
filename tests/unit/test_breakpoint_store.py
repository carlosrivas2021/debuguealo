import pytest

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.breakpoints import BreakpointStore


def test_store_absence_is_empty_and_does_not_create_file(tmp_path):
    store = BreakpointStore(tmp_path / "breakpoints.json")
    assert store.load() == {}
    assert not store.path.exists()


def test_store_round_trips_canonical_sorted_unique_marks(tmp_path):
    store = BreakpointStore(tmp_path / "breakpoints.json")
    root = tmp_path / "project"
    root.mkdir()
    source = root / "main.py"
    store.save({(root, source): set([4, 2, 4])})
    assert store.load() == {(root.resolve(), source.resolve()): (2, 4)}


def test_store_malformed_file_is_preserved(tmp_path):
    path = tmp_path / "breakpoints.json"
    path.write_bytes(b"{broken")
    before = path.read_bytes()
    store = BreakpointStore(path)
    with pytest.raises(ConfigurationError, match="Invalid Code breakpoints"):
        store.load()
    with pytest.raises(ConfigurationError, match="Invalid Code breakpoints"):
        store.save({})
    assert path.read_bytes() == before


def test_store_rejects_invalid_lines_without_publishing(tmp_path):
    path = tmp_path / "breakpoints.json"
    store = BreakpointStore(path)
    root = tmp_path / "project"
    root.mkdir()
    with pytest.raises(ConfigurationError):
        store.save({(root, root / "main.py"): {0, 3}})
    assert not path.exists()
