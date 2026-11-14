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


def _project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root.resolve(), (root / "main.py").resolve()


def test_store_round_trips_condition_and_log_message(tmp_path):
    from debugpilot.storage.breakpoints import BreakpointOptions

    store = BreakpointStore(tmp_path / "breakpoints.json")
    root, source = _project(tmp_path)
    options = {(root, source): {
        3: BreakpointOptions(condition="user_id == 42"),
        7: BreakpointOptions(log_message="order {order.id} received"),
        9: BreakpointOptions(condition="n > 1", log_message="n={n}"),
    }}
    store.save({(root, source): {2, 3, 7, 9}}, options)
    assert store.load() == {(root, source): (2, 3, 7, 9)}
    assert store.load_options() == options


def test_store_without_options_writes_the_previous_format(tmp_path):
    import json

    store = BreakpointStore(tmp_path / "breakpoints.json")
    root, source = _project(tmp_path)
    store.save({(root, source): {2, 4}})
    expected = {"version": 1, "breakpoints": [
        {"root": str(root), "file": str(source), "lines": [2, 4]}]}
    assert store.path.read_bytes() == (json.dumps(expected, indent=2) + "\n").encode()
    assert store.load_options() == {}


def test_store_loads_a_file_written_before_options_existed(tmp_path):
    import json

    root, source = _project(tmp_path)
    path = tmp_path / "breakpoints.json"
    path.write_text(json.dumps({"version": 1, "breakpoints": [
        {"root": str(root), "file": str(source), "lines": [5]}]}))
    store = BreakpointStore(path)
    assert store.load() == {(root, source): (5,)}
    assert store.load_options() == {}


@pytest.mark.parametrize("options", [
    {},
    {"5": {}},
    {"6": {"condition": "x"}},
    {"5": {"condition": ""}},
    {"5": {"condition": 3}},
    {"5": {"hitCount": "2"}},
    {"x": {"condition": "x"}},
    {"5": {"condition": "x" * 1001}},
    {"05": {"condition": "x"}},
    {"\u0665": {"condition": "x"}},
], ids=["empty", "no-fields", "line-without-mark", "blank", "not-text", "unknown-field",
        "bad-line", "too-long", "zero-padded-line", "non-ascii-digit"])
def test_store_rejects_invalid_options_and_keeps_the_file(tmp_path, options):
    import json

    root, source = _project(tmp_path)
    path = tmp_path / "breakpoints.json"
    path.write_text(json.dumps({"version": 1, "breakpoints": [
        {"root": str(root), "file": str(source), "lines": [5], "options": options}]}))
    before = path.read_bytes()
    store = BreakpointStore(path)
    with pytest.raises(ConfigurationError, match="Invalid Code breakpoints"):
        store.load_options()
    with pytest.raises(ConfigurationError, match="Invalid Code breakpoints"):
        store.save({})
    assert path.read_bytes() == before


def test_store_drops_options_of_lines_without_a_breakpoint(tmp_path):
    from debugpilot.storage.breakpoints import BreakpointOptions

    store = BreakpointStore(tmp_path / "breakpoints.json")
    root, source = _project(tmp_path)
    other = (root / "other.py").resolve()
    store.save({(root, source): {2}}, {
        (root, source): {2: BreakpointOptions(condition="a"),
                         8: BreakpointOptions(condition="gone")},
        (root, other): {1: BreakpointOptions(condition="no marks")},
    })
    assert store.load_options() == {(root, source): {2: BreakpointOptions(condition="a")}}


def test_breakpoint_options_normalizes_blank_fields():
    from debugpilot.storage.breakpoints import BreakpointOptions, breakpoint_options

    assert breakpoint_options("  ", "") is None
    assert breakpoint_options(" x > 1 ", " ") == BreakpointOptions(condition="x > 1")
    assert breakpoint_options(None, "hit {n}") == BreakpointOptions(log_message="hit {n}")
    with pytest.raises(ValueError):
        breakpoint_options("x" * 1001, None)
    # The limit applies to the trimmed text.
    assert breakpoint_options(" " + "x" * 1000, None) == BreakpointOptions(condition="x" * 1000)


def test_save_with_invalid_options_keeps_the_existing_file(tmp_path):
    from debugpilot.storage.breakpoints import BreakpointOptions

    store = BreakpointStore(tmp_path / "breakpoints.json")
    root, source = _project(tmp_path)
    store.save({(root, source): {2}}, {(root, source): {2: BreakpointOptions(condition="a")}})
    before = store.path.read_bytes()
    with pytest.raises(ConfigurationError, match="Cannot save Code breakpoints"):
        store.save({(root, source): {2}},
                   {(root, source): {2: BreakpointOptions(condition="x" * 1001)}})
    assert store.path.read_bytes() == before


def test_save_ignores_options_of_files_without_marks_even_with_unusable_paths(tmp_path):
    from debugpilot.storage.breakpoints import BreakpointOptions

    store = BreakpointStore(tmp_path / "breakpoints.json")
    root, source = _project(tmp_path)
    store.save({(root, source): {2}}, {
        (root, source): {2: BreakpointOptions(condition="kept")},
        ("relative", "path.py"): {1: BreakpointOptions(condition="no marks")},
    })
    assert store.load_options() == {(root, source): {2: BreakpointOptions(condition="kept")}}


def test_store_round_trips_hit_conditions(tmp_path):
    import json

    from debugpilot.storage.breakpoints import BreakpointOptions

    store = BreakpointStore(tmp_path / "breakpoints.json")
    root, source = _project(tmp_path)
    options = {(root, source): {
        3: BreakpointOptions(hit_condition=">=5"),
        7: BreakpointOptions(log_message="n={n}", hit_condition="%2"),
    }}
    store.save({(root, source): {3, 7}}, options)
    assert store.load_options() == options
    saved = json.loads(store.path.read_text())["breakpoints"][0]["options"]
    assert saved == {"3": {"hitCondition": ">=5"},
                     "7": {"logMessage": "n={n}", "hitCondition": "%2"}}


@pytest.mark.parametrize(("text", "expected"), [
    ("5", "5"), (" 12 ", "12"), ("==3", "==3"), ("> 1", ">1"), (">= 10", ">=10"),
    ("<4", "<4"), ("<=4", "<=4"), ("% 3", "%3"), (">0", ">0"),
])
def test_hit_condition_accepts_counts_and_comparisons(text, expected):
    from debugpilot.storage.breakpoints import BreakpointOptions, breakpoint_options

    assert breakpoint_options(None, None, text) == BreakpointOptions(hit_condition=expected)


@pytest.mark.parametrize("text", [
    "x", "!=3", "%0", "0", "=3", ">=", "3.5", "-2", "5 5", "1" * 10, "\u0665", ">=\u0663",
])
def test_hit_condition_rejects_other_text(text):
    from debugpilot.storage.breakpoints import breakpoint_options

    with pytest.raises(ValueError, match="Hit count"):
        breakpoint_options(None, None, text)


def test_condition_and_hit_count_cannot_be_combined():
    from debugpilot.storage.breakpoints import breakpoint_options

    with pytest.raises(ValueError, match="condition or a hit count, not both"):
        breakpoint_options("x > 1", None, "3")
    assert breakpoint_options(None, None, "  ") is None


def test_store_rejects_a_stored_condition_with_a_hit_count(tmp_path):
    import json

    root, source = _project(tmp_path)
    path = tmp_path / "breakpoints.json"
    path.write_text(json.dumps({"version": 1, "breakpoints": [
        {"root": str(root), "file": str(source), "lines": [5],
         "options": {"5": {"condition": "x", "hitCondition": "2"}}}]}))
    with pytest.raises(ConfigurationError, match="Invalid Code breakpoints"):
        BreakpointStore(path).load_options()
