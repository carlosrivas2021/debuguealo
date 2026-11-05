"""Public configuration contract for optional non-owning Go attach profiles."""

import json

import pytest

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.code_projects import CodeProjectStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'debugpilot.storage.code_projects.config_path', lambda: tmp_path / 'config.toml')
    result = CodeProjectStore()
    result.ensure_launch_file()
    return result


def test_valid_attach_profile_without_command_has_empty_argv_and_keeps_launch_profiles(
        store, tmp_path):
    existing = {'name': 'Python', 'workspaceFolder': str(tmp_path),
                'command': ['python', 'main.py'], 'extra': {'keep': True}}
    document = {'version': 1, 'configurations': [existing, {
        'name': 'Go remote', 'workspaceFolder': str(tmp_path),
        'goAttach': {'host': '127.0.0.1', 'port': 2345, 'remoteRoot': '/app'},
    }]}
    store.path.write_text(json.dumps(document), encoding='utf-8')
    before = store.path.read_bytes()

    profiles = store.profiles()

    assert [(p.name, p.command) for p in profiles] == [('Python', ('python', 'main.py')),
                                                       ('Go remote', ())]
    attach = profiles[1].go_attach
    assert (attach.host, attach.port, attach.remote_root) == ('127.0.0.1', 2345, '/app')
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('attach', [
    {},
    {'port': 2345, 'remoteRoot': '/app'},
    {'host': 'localhost', 'port': 2345, 'remoteRoot': '/app'},
    {'host': '0.0.0.0', 'port': 2345, 'remoteRoot': '/app'},
    {'host': '127.0.0.1', 'port': True, 'remoteRoot': '/app'},
    {'host': '127.0.0.1', 'port': 0, 'remoteRoot': '/app'},
    {'host': '127.0.0.1', 'port': 65536, 'remoteRoot': '/app'},
    {'host': '127.0.0.1', 'port': '2345', 'remoteRoot': '/app'},
    {'host': '127.0.0.1', 'port': 2345, 'remoteRoot': 'app'},
    {'host': '127.0.0.1', 'port': 2345, 'remoteRoot': 'C:/app'},
    {'host': '127.0.0.1', 'port': 2345, 'remoteRoot': '/app/../outside'},
    {'host': '127.0.0.1', 'port': 2345, 'remoteRoot': r'\app'},
])
def test_rejects_invalid_go_attach_without_mutating_profile_file(store, tmp_path, attach):
    store.path.write_text(json.dumps({'version': 1, 'configurations': [{
        'name': 'bad', 'workspaceFolder': str(tmp_path), 'goAttach': attach,
    }]}), encoding='utf-8')
    before = store.path.read_bytes()

    with pytest.raises(ConfigurationError) as error:
        store.profiles()

    assert str(error.value) == (
        'Invalid goAttach: use host 127.0.0.1, integer port 1..65535, and an absolute POSIX '
        'remoteRoot without parent segments.'
    )
    assert store.path.read_bytes() == before


def test_attach_only_requires_go_attach_and_existing_profiles_still_require_command(
        store, tmp_path):
    for entry in (
            {'name': 'missing', 'workspaceFolder': str(tmp_path)},
            {'name': 'empty', 'workspaceFolder': str(tmp_path), 'command': []}):
        store.path.write_text(json.dumps({'version': 1, 'configurations': [entry]}),
                              encoding='utf-8')
        before = store.path.read_bytes()
        with pytest.raises(ConfigurationError):
            store.profiles()
        assert store.path.read_bytes() == before


def test_existing_go_command_profile_retains_argv_and_has_no_attach(store, tmp_path):
    store.path.write_text(json.dumps({'version': 1, 'configurations': [{
        'name': 'Go launch', 'workspaceFolder': str(tmp_path),
        'command': ['go', 'run', 'main.go', 'arg'],
    }]}), encoding='utf-8')

    profile = store.profiles()[0]

    assert profile.command == ('go', 'run', 'main.go', 'arg')
    assert profile.go_attach is None
