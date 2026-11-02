import json
import os
import stat
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
    assert target.read_bytes() == b'{\n  "version": 1,\n  "configurations": []\n}\n'


def test_editor_success_prettifies_valid_json_preserving_order_unknown_fields_and_unicode(
    tmp_path, monkeypatch
):
    target = tmp_path / "launch.json"
    target.write_bytes('{"z":"café 🐳","custom":{"keep":true},"version":1}'.encode())
    monkeypatch.setattr(launch_file.shutil, "which", lambda _name: "/tools/nano")
    monkeypatch.setattr(
        launch_file.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )

    launch_file.open_launch_file(target)

    assert target.read_bytes() == (
        '{\n  "z": "café 🐳",\n  "custom": {\n    "keep": true\n  },\n  "version": 1\n}\n'
    ).encode()


def test_editor_success_formats_without_fchmod_preserves_mode_and_cleans_temp(
    tmp_path, monkeypatch
):
    target = tmp_path / "launch.json"
    target.write_bytes(b'{"version":1}')
    os.chmod(target, 0o640)
    original_mode = stat.S_IMODE(target.stat().st_mode)
    monkeypatch.setattr(launch_file.shutil, "which", lambda _name: "/tools/nano")
    monkeypatch.setattr(
        launch_file.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    monkeypatch.delattr(launch_file.os, "fchmod", raising=False)

    launch_file.open_launch_file(target)

    assert target.read_bytes() == b'{\n  "version": 1\n}\n'
    assert stat.S_IMODE(target.stat().st_mode) == original_mode
    assert list(tmp_path.iterdir()) == [target]


def test_invalid_json_after_editor_is_preserved_and_reports_line_and_column_without_content(
    tmp_path, monkeypatch
):
    target = tmp_path / "launch.json"
    invalid = b'{\n  "secret": "do-not-show",\n  broken\n}'
    target.write_bytes(b"{}")
    monkeypatch.setattr(launch_file.shutil, "which", lambda _name: "/tools/nano")

    def edit(args, **kwargs):
        target.write_bytes(invalid)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(launch_file.subprocess, "run", edit)
    with pytest.raises(ConfigurationError) as error:
        launch_file.open_launch_file(target)

    assert str(error.value) == "Invalid JSON in launch.json at line 3, column 3."
    assert b"do-not-show" not in str(error.value).encode()
    assert target.read_bytes() == invalid


def test_concurrent_newer_write_is_not_replaced_by_formatted_editor_snapshot(tmp_path, monkeypatch):
    target = tmp_path / "launch.json"
    target.write_bytes(b'{"version":1}')
    newer = b'{"version":2}'
    monkeypatch.setattr(launch_file.shutil, "which", lambda _name: "/tools/nano")
    monkeypatch.setattr(
        launch_file.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    real_formatter = launch_file._pretty_json_tokens

    def write_newer_before_atomic_replace(tokens):
        formatted = real_formatter(tokens)
        target.write_bytes(newer)
        return formatted

    monkeypatch.setattr(launch_file, "_pretty_json_tokens", write_newer_before_atomic_replace)

    with pytest.raises(ConfigurationError, match="newer contents were left untouched"):
        launch_file.open_launch_file(target)

    assert target.read_bytes() == newer


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
