import json
import subprocess

import pytest

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.launch_profiles import LaunchProfileStore
from debugpilot.tui import launch_file


def make_example(workspace):
    example = workspace / "examples" / "multi-project" / "catalog" / "compose.yaml"
    example.parent.mkdir(parents=True)
    example.write_text("name: dp-demo-catalog\nservices: {}\n")
    return example


def test_ensure_launch_file_creates_resolvable_real_example_profile(tmp_path):
    example = make_example(tmp_path)
    store = LaunchProfileStore(tmp_path)

    path = store.ensure_launch_file()

    assert path == tmp_path / ".debugpilot" / "launch.json"
    document = json.loads(path.read_text())
    assert document["version"] == 1
    (profile,) = document["configurations"]
    assert profile["name"] == "Catalog example"
    assert profile["projectName"] == "dp-demo-catalog"
    assert profile["cwd"] == "${workspaceFolder}"
    assert profile["files"] == ["examples/multi-project/catalog/compose.yaml"]
    assert profile["up"] == {"build": True, "detach": True, "forceRecreate": True}
    assert list(path.parent.glob("*.json")) == [path]
    resolved = store.resolve(store.profiles()[0])
    assert resolved is not None
    assert resolved.files == (example.resolve(),)
    assert resolved.project_directory == example.parent.resolve()


def test_ensure_launch_file_uses_empty_template_when_example_is_missing(tmp_path):
    store = LaunchProfileStore(tmp_path)

    path = store.ensure_launch_file()

    assert json.loads(path.read_text()) == {"version": 1, "configurations": []}
    assert "examples" not in path.read_text()


def test_ensure_launch_file_returns_existing_malformed_file_unchanged(tmp_path):
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    before = b'{"broken":'
    store.path.write_bytes(before)

    assert store.ensure_launch_file() == store.path
    assert store.path.read_bytes() == before


def test_editor_creation_race_is_not_overwritten(tmp_path, monkeypatch):
    make_example(tmp_path)
    store = LaunchProfileStore(tmp_path)
    concurrent = b'{"version":1,"configurations":[{"name":"Editor save"}]}'

    def race(_temporary, target):
        target.write_bytes(concurrent)
        raise FileExistsError

    monkeypatch.setattr("debugpilot.storage.launch_profiles.os.link", race)
    assert store.ensure_launch_file() == store.path
    assert store.path.read_bytes() == concurrent


def test_symlinked_launch_target_fails_closed(tmp_path):
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    other = tmp_path / "other.json"
    other.write_text("{}")
    try:
        store.path.symlink_to(other)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")

    with pytest.raises(ConfigurationError, match="symlinks"):
        store.ensure_launch_file()
    assert other.read_text() == "{}"


@pytest.mark.parametrize(
    "available, expected",
    [
        ({"nano": "/tools/nano", "vi": "/tools/vi"}, "/tools/nano"),
        ({"vi": "/tools/vi"}, "/tools/vi"),
    ],
)
def test_terminal_editor_inherits_terminal_and_waits(tmp_path, monkeypatch, available, expected):
    target = tmp_path / "path with spaces" / "launch.json"
    target.parent.mkdir()
    target.write_text("{}")
    calls = []
    monkeypatch.setattr(launch_file.shutil, "which", available.get)

    def run(args, **kwargs):
        calls.append((args, kwargs))
        target.write_text('{"version":1,"configurations":[]}')
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(launch_file.subprocess, "run", run)
    launch_file.open_launch_file(target)

    assert calls == [([expected, str(target.resolve())], {"shell": False, "check": False})]
    assert json.loads(target.read_text()) == {"version": 1, "configurations": []}


def test_editor_nonzero_exit_is_reported_without_launching_another_editor(tmp_path, monkeypatch):
    target = tmp_path / "launch.json"
    target.write_text("{}")
    calls = []
    monkeypatch.setattr(launch_file.shutil, "which", lambda name: "/tools/" + name)

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 2)

    monkeypatch.setattr(launch_file.subprocess, "run", run)
    with pytest.raises(ConfigurationError, match="exited with status 2"):
        launch_file.open_launch_file(target)
    assert calls == [["/tools/nano", str(target)]]
    assert target.read_text() == "{}"


def test_editor_failure_is_actionable_and_does_not_mutate_file(tmp_path, monkeypatch):
    target = tmp_path / "launch.json"
    target.write_text('{"version":1,"configurations":[]}')
    before = target.read_bytes()
    monkeypatch.setattr(launch_file.shutil, "which", lambda _name: None)

    with pytest.raises(ConfigurationError, match="Install nano or vi"):
        launch_file.open_launch_file(target)
    assert target.read_bytes() == before
