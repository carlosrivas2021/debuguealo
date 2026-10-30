import json
import os

import pytest

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.launch_profiles import LaunchProfileStore


def service(identity, project="demo", *, working_dir=None, files=None, environment_file=None):
    labels = {"com.docker.compose.project": project}
    if working_dir is not None:
        labels["com.docker.compose.project.working_dir"] = str(working_dir)
    if files is not None:
        labels["com.docker.compose.project.config_files"] = ",".join(map(str, files))
    if environment_file is not None:
        labels["com.docker.compose.project.environment_file"] = str(environment_file)
    return type(
        "Container",
        (),
        {"id": identity, "name": f"{project}-{identity}", "labels": labels},
    )()


def workspace_files(root):
    (root / "local" / "agents").mkdir(parents=True)
    (root / "local" / "agents" / "docker-compose.yaml").write_text("services: {}\n")
    (root / "agents.ports.yaml").write_text("services: {}\n")


def test_default_store_uses_central_path_across_cwd_and_resolves_explicit_external_root(
    tmp_path, monkeypatch
):
    config_root = tmp_path / "settings"
    monkeypatch.setattr(
        "debugpilot.storage.launch_profiles.config_path", lambda: config_root / "config.toml"
    )
    project = tmp_path / "external"
    (project / "local" / "agente").mkdir(parents=True)
    compose = project / "local" / "agente" / "docker-compose.yaml"
    compose.write_text("services: {}\\n")
    monkeypatch.chdir(tmp_path)
    first = LaunchProfileStore()
    monkeypatch.chdir(project)
    second = LaunchProfileStore()
    assert first.path == second.path == config_root / "launch.json"
    assert not first.path.parent.exists()

    profile = {
        "name": "Agente",
        "type": "docker-compose",
        "projectName": "local-agente",
        "workspaceFolder": str(project),
        "cwd": "${workspaceFolder}",
        "files": ["local/agente/docker-compose.yaml"],
    }
    from debugpilot.storage.launch_profiles import LaunchProfile

    resolved = first.resolve(LaunchProfile("Agente", "local-agente", None, profile))
    assert resolved is not None
    assert resolved.workspace == project.resolve()
    assert resolved.cwd == project.resolve()
    assert resolved.files == (compose.resolve(),)


def test_default_store_rejects_external_paths_without_explicit_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "debugpilot.storage.launch_profiles.config_path",
        lambda: tmp_path / "settings" / "config.toml",
    )
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\\n")
    store = LaunchProfileStore()
    from debugpilot.storage.launch_profiles import LaunchProfile

    profile = LaunchProfile(
        "Bad",
        "demo",
        None,
        {
            "type": "docker-compose",
            "projectName": "demo",
            "cwd": str(tmp_path),
            "files": [str(compose)],
        },
    )
    assert store.resolve(profile) is None


def test_explicit_workspace_store_remains_local(tmp_path):
    store = LaunchProfileStore(tmp_path)
    assert store.path == tmp_path / ".debugpilot" / "launch.json"


def test_dynamic_discovery_creates_no_files_and_saved_profile_wins(tmp_path):
    store = LaunchProfileStore(tmp_path)
    assert store.register([service("a")]) is True
    assert len(store.profiles()) == 1
    assert not store.path.parent.exists()
    assert LaunchProfileStore(tmp_path).profiles() == []
    store.path.parent.mkdir()
    saved = {"version": 1, "configurations": [{"projectName": "demo", "name": "Mine"}]}
    original = json.dumps(saved).encode()
    store.path.write_bytes(original)
    store.register([service("b")])
    assert [p.name for p in store.profiles()] == ["Mine"]
    assert store.path.read_bytes() == original
    store.register([])
    assert store.load() == saved


def test_explicit_save_creates_only_missing_launch_and_preserves_editor_save(tmp_path, monkeypatch):
    store = LaunchProfileStore(tmp_path)
    raw = {"name": "Saved", "projectName": "demo", "type": "docker-compose"}
    store.save_configuration(raw)
    original = store.path.read_bytes()
    assert store.load()["configurations"][0]["name"] == "Saved"
    with pytest.raises(ConfigurationError):
        store.save_configuration({**raw, "name": "Other"})
    assert store.path.read_bytes() == original

    (tmp_path / "nested").mkdir()
    second = LaunchProfileStore(tmp_path / "nested")
    real_link = os.link
    editor_bytes = b'{"version":1,"configurations":[],"custom":"editor"}'

    def editor_creates_before_publish(source, destination):
        second.path.write_bytes(editor_bytes)
        return real_link(source, destination)

    monkeypatch.setattr("debugpilot.storage.launch_profiles.os.link", editor_creates_before_publish)
    with pytest.raises(ConfigurationError):
        second.save_configuration(raw)
    assert second.path.read_bytes() == editor_bytes
    assert list(second.path.parent.iterdir()) == [second.path]


def test_registers_external_project_once_and_preserves_user_fields(tmp_path):
    workspace_files(tmp_path)
    store = LaunchProfileStore(tmp_path)
    detected = service(
        "first-id",
        working_dir=tmp_path,
        files=["local/agents/docker-compose.yaml", "agents.ports.yaml"],
    )

    assert store.register([detected]) is True
    doc = store.load()
    store.path.parent.mkdir()
    doc["customRoot"] = {"keep": True}
    doc["configurations"][0]["customConfig"] = "preserve"
    store.path.write_text(json.dumps(doc, indent=2) + "\n")
    original = store.path.read_bytes()
    doc = store.load()
    assert doc["version"] == 1
    assert len(doc["configurations"]) == 1
    profile = doc["configurations"][0]
    assert profile["type"] == "docker-compose"
    assert profile["source"] == "discovered"
    assert profile["projectName"] == "demo"
    assert profile["files"] == ["local/agents/docker-compose.yaml", "agents.ports.yaml"]
    assert profile["projectDirectory"] == "${workspaceFolder}"

    recreated = service(
        "replacement-id",
        working_dir=tmp_path,
        files=["local/agents/docker-compose.yaml", "agents.ports.yaml"],
    )
    assert store.register([detected, recreated]) is False
    assert store.path.read_bytes() == original

    profile["name"] = "My Debug Name"
    profile["up"] = {"build": True, "detach": True, "forceRecreate": False}
    store.path.write_text(json.dumps(doc, indent=2) + "\n")
    assert store.register([recreated]) is False
    assert store.load()["customRoot"] == {"keep": True}
    assert store.load()["configurations"][0]["customConfig"] == "preserve"
    assert store.load()["configurations"][0]["name"] == "My Debug Name"
    assert store.load()["configurations"][0]["up"]["build"] is True


def test_group_conflicts_and_untrusted_paths_stay_pending_without_external_writes(tmp_path):
    workspace_files(tmp_path)
    outside = tmp_path.parent / f"external-{tmp_path.name}"
    outside.mkdir()
    store = LaunchProfileStore(tmp_path)
    a = service("a", working_dir=tmp_path, files=["local/agents/docker-compose.yaml"])
    b = service("b", working_dir=tmp_path, files=["agents.ports.yaml"])

    assert store.register([a, b]) is True
    (profile,) = store.profiles("demo")
    assert profile.pending_reason
    assert store.resolve(profile) is None

    (tmp_path / "nested").mkdir()
    store2 = LaunchProfileStore(tmp_path / "nested")
    foreign = service("foreign", working_dir=outside, files=[outside / "compose.yaml"])
    assert store2.register([foreign]) is True
    (pending,) = store2.profiles("demo")
    assert pending.pending_reason
    assert not (outside / ".debugpilot").exists()


def test_missing_metadata_registers_pending_profile_and_load_never_writes(tmp_path):
    store = LaunchProfileStore(tmp_path)
    assert store.profiles() == []
    assert not store.path.exists()
    assert store.register([service("unknown")]) is True
    (profile,) = store.profiles()
    assert profile.pending_reason
    assert store.resolve(profile) is None


@pytest.mark.parametrize("existing_count", [127, 128])
def test_registration_respects_configuration_limit_without_changing_existing_data(
    tmp_path, existing_count
):
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    document = {
        "version": 1,
        "customRoot": "preserve",
        "configurations": [
            {"projectName": f"project-{i}", "custom": i} for i in range(existing_count)
        ],
    }
    original = json.dumps(document).encode()
    store.path.write_bytes(original)

    if existing_count == 128:
        with pytest.raises(ConfigurationError, match="128"):
            store.register([service("new", project="new-project")])
        assert store.path.read_bytes() == original
        assert store.load() == document
    else:
        assert store.register([service("new", project="new-project")]) is True
        result = store.load()
        assert len(result["configurations"]) == 128
        assert result["configurations"][:existing_count] == document["configurations"]
        assert result["customRoot"] == "preserve"
        assert store.register([service("recreated", project="new-project")]) is False


def test_oversized_discovery_batch_does_not_create_registry(tmp_path):
    store = LaunchProfileStore(tmp_path)
    inventory = [service(str(i), project=f"project-{i}") for i in range(129)]
    with pytest.raises(ConfigurationError, match="128"):
        store.register(inventory)
    assert not store.path.parent.exists()
    assert store.load() == {"version": 1, "configurations": []}


def test_resolves_nested_paths_and_only_workspace_folder_variable(tmp_path):
    workspace_files(tmp_path)
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "customRoot": {"keep": True},
                "configurations": [
                    {
                        "name": "Nested",
                        "type": "docker-compose",
                        "projectName": "demo",
                        "cwd": "${workspaceFolder}",
                        "files": ["local/agents/docker-compose.yaml", "agents.ports.yaml"],
                        "up": {"build": True, "detach": False, "forceRecreate": True},
                    }
                ],
            }
        )
    )
    (profile,) = store.profiles("demo")
    resolved = store.resolve(profile)
    assert resolved.workspace == tmp_path
    assert resolved.cwd == tmp_path
    assert resolved.files == (
        tmp_path / "local" / "agents" / "docker-compose.yaml",
        tmp_path / "agents.ports.yaml",
    )
    assert resolved.project_directory == tmp_path / "local" / "agents"
    assert resolved.up == {"build": True, "detach": False, "forceRecreate": True}

    profile.raw["cwd"] = "${HOME}"
    assert store.resolve(profile) is None
    assert "${HOME}" not in store.path.read_text()


@pytest.mark.parametrize(
    "contents",
    [b"{", b'{"version":2,"configurations":[]}', b'{"version":1,"configurations":[null]}'],
)
def test_invalid_documents_are_never_overwritten(tmp_path, contents):
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    store.path.write_bytes(contents)
    before = store.path.read_bytes()
    with pytest.raises(ConfigurationError):
        store.load()
    with pytest.raises(ConfigurationError):
        store.register([service("x", working_dir=tmp_path, files=["compose.yaml"])])
    assert store.path.read_bytes() == before


def test_oversized_document_is_preserved(tmp_path):
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    contents = b" " * (256 * 1024 + 1)
    store.path.write_bytes(contents)
    with pytest.raises(ConfigurationError):
        store.register([service("x")])
    assert store.path.read_bytes() == contents


def test_symlink_destination_is_rejected(tmp_path):
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    target = tmp_path / "elsewhere.json"
    target.write_text('{"version":1,"configurations":[]}')
    try:
        store.path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")
    before = target.read_bytes()
    with pytest.raises(ConfigurationError):
        store.register([service("x")])
    assert target.read_bytes() == before


def test_discovery_never_calls_writer_or_replaces_editor_file(tmp_path, monkeypatch):
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    editor_bytes = b'{"version":1,"configurations":[],"custom":"editor-save"}'
    store.path.write_bytes(editor_bytes)

    def deny(*_args):
        pytest.fail("Discovery must not call a filesystem writer")

    monkeypatch.setattr("debugpilot.storage.launch_profiles.os.replace", deny)
    monkeypatch.setattr("debugpilot.storage.launch_profiles.os.fsync", deny)
    assert store.register([service("x")]) is True
    assert store.path.read_bytes() == editor_bytes
    assert list(store.path.parent.iterdir()) == [store.path]


def test_user_can_resolve_pending_discovery_by_editing_paths(tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}")
    store = LaunchProfileStore(tmp_path)
    missing = service("x")
    store.register([missing])
    assert store.profiles()[0].pending_reason
    document = store.load()
    profile = document["configurations"][0]
    profile.update(cwd="${workspaceFolder}", files=["compose.yaml"], custom="keep", source="manual")
    profile.pop("pendingReason", None)
    store.path.parent.mkdir()
    store.path.write_text(json.dumps(document))
    store.register([missing])
    assert store.profiles()[0].pending_reason is None
    assert store.load()["configurations"][0]["custom"] == "keep"
    assert store.load()["configurations"][0]["source"] == "manual"


@pytest.mark.parametrize("manual", [False, True])
def test_removed_environment_hint_reconciles_only_pristine_generated_fields(tmp_path, manual):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}")
    old_env = tmp_path / "old.env"
    old_env.write_text("MODE=old")
    custom_env = tmp_path / "custom.env"
    custom_env.write_text("MODE=custom")
    store = LaunchProfileStore(tmp_path)
    store.register(
        [service("old", working_dir=tmp_path, files=[compose], environment_file=old_env)]
    )
    if manual:
        document = store.load()
        document["configurations"][0]["environmentFiles"] = ["custom.env"]
        store.path.parent.mkdir()
        store.path.write_text(json.dumps(document))
    store.register([service("new-id", working_dir=tmp_path, files=[compose])])
    profile = store.profiles()[0]
    assert profile.pending_reason is None
    assert store.resolve(profile).environment_files == ((custom_env,) if manual else ())
