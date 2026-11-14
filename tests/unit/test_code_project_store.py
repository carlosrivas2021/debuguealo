import json

import pytest

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.code_projects import CodeProjectStore
from debugpilot.storage.launch_profiles import LaunchProfileStore


@pytest.mark.parametrize('target', [
    None, ['node', 'server.js', '--literal'], ['node', 'src/main.ts'],
])
def test_optional_npm_node_target_retains_original_argv(tmp_path, monkeypatch, target):
    store = configure(monkeypatch, tmp_path)
    entry = {'name': 'npm', 'workspaceFolder': str(tmp_path), 'command': ['npm', 'run', 'dev']}
    if target is not None:
        entry['nodeDebug'] = target
    store.path.write_text(json.dumps({'version': 1, 'configurations': [entry]}))
    original = store.path.read_bytes()
    profile = store.profiles()[0]
    assert profile.command == ('npm', 'run', 'dev')
    assert profile.node_debug == (tuple(target) if target else None)
    assert store.path.read_bytes() == original


@pytest.mark.parametrize('command,target', [
    (['python', 'main.py'], ['node', 'server.js']),
    (['npm', 'run', 'dev'], []), (['npm', 'run', 'dev'], 'node server.js'),
    (['npm', 'run', 'dev'], ['node', '-e', 'bad']),
    (['npm', 'run', 'dev'], ['other', 'server.js']),
    (['npm', 'run', 'dev'], ['node', 'server.js', '']),
    (['npm', 'run', 'dev'], ['node', 'src/App.tsx']),
])
def test_invalid_node_metadata_is_rejected_unchanged(tmp_path, monkeypatch, command, target):
    store = configure(monkeypatch, tmp_path)
    container_store = LaunchProfileStore(tmp_path)
    container_store.ensure_launch_file()
    container_bytes = container_store.path.read_bytes()
    entry = {'name': 'bad', 'workspaceFolder': str(tmp_path), 'command': command,
             'nodeDebug': target}
    store.path.write_text(json.dumps({'version': 1, 'configurations': [entry]}))
    original = store.path.read_bytes()
    with pytest.raises(ConfigurationError, match='nodeDebug'):
        store.profiles()
    assert store.path.read_bytes() == original
    assert container_store.path.read_bytes() == container_bytes


def test_default_code_configuration_is_isolated_by_fixture(tmp_path):
    assert CodeProjectStore().path == tmp_path / ".debugpilot" / "projects" / "launch.json"


def configure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "debugpilot.storage.code_projects.config_path", lambda: tmp_path / "config.toml"
    )
    store = CodeProjectStore()
    store.ensure_launch_file()
    return store


def test_two_explicit_roots_are_central_and_independent_of_cwd(tmp_path, monkeypatch):
    store = configure(monkeypatch, tmp_path)
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir()
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "configurations": [
                    {
                        "name": root.name,
                        "workspaceFolder": str(root),
                        "command": ["python", "main.py"],
                    }
                    for root in roots
                ],
            }
        ),
        encoding="utf-8",
    )
    before = store.path.read_bytes()
    monkeypatch.chdir(roots[1])
    assert CodeProjectStore().path == tmp_path / "projects" / "launch.json"
    profiles = CodeProjectStore().profiles()
    assert [(p.name, p.root, p.command) for p in profiles] == [
        (root.name, root.resolve(), ("python", "main.py")) for root in roots
    ]
    assert store.path.read_bytes() == before


@pytest.mark.parametrize(
    "document",
    [
        "{",
        {"version": True, "configurations": []},
        {"version": 1, "configurations": [{}]},
        {
            "version": 1,
            "configurations": [{"name": "x", "workspaceFolder": "relative", "command": ["python"]}],
        },
        {
            "version": 1,
            "configurations": [{"name": "x", "workspaceFolder": "ROOT", "command": "npm run dev"}],
        },
        {"version": 1, "configurations": [{"name": "x", "workspaceFolder": "ROOT", "command": []}]},
    ],
)
def test_bad_code_profiles_leave_both_files_unchanged(tmp_path, monkeypatch, document):
    store = configure(monkeypatch, tmp_path)
    container_store = LaunchProfileStore(tmp_path)
    container_store.ensure_launch_file()
    container_bytes = container_store.path.read_bytes()
    payload = (
        document
        if isinstance(document, str)
        else json.dumps(document).replace("ROOT", tmp_path.as_posix())
    )
    store.path.write_text(payload, encoding="utf-8")
    before = store.path.read_bytes()
    with pytest.raises(ConfigurationError) as error:
        store.profiles()
    assert str(error.value) == (
        "Invalid code launch.json: use version 1 and up to 128 configurations with "
        "unique names, existing absolute workspaceFolder directories and nonempty "
        "command argument arrays."
    )
    assert store.ensure_launch_file() == store.path
    assert store.path.read_bytes() == before
    assert container_store.path.read_bytes() == container_bytes
    assert container_store.profiles() == []
