import json

import pytest

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.docker.compose import ComposeError, ComposeProject
from debugpilot.storage.compose_projects import ComposeProjectStore


def project(tmp_path, name="catalog"):
    (tmp_path / "compose.yaml").write_text("services: {}")
    (tmp_path / "local.yaml").write_text("services: {}")
    return ComposeProject.create(tmp_path, ("compose.yaml", "local.yaml"), name)


def test_round_trip_preserves_project_paths_and_override_order(tmp_path):
    target = tmp_path / "settings" / "compose-projects.json"
    store = ComposeProjectStore(target)
    assert store.load() == {}
    selected = project(tmp_path)
    store.save(selected)
    document = json.loads(target.read_text())
    assert document == {
        "version": 1,
        "projects": [
            {
                "name": "catalog",
                "workspace": str(selected.workspace),
                "files": [str(file) for file in selected.files],
            }
        ],
    }
    assert ComposeProjectStore(target).load()["catalog"].resolve() == selected
    store.save(project(tmp_path, "orders"))
    assert set(store.load()) == {"catalog", "orders"}
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "text",
    ["{", '{"version":2,"projects":[]}', '{"version":1,"projects":[],"token":"x"}'],
)
def test_invalid_config_is_reported_and_never_overwritten(tmp_path, text):
    target = tmp_path / "compose-projects.json"
    target.write_text(text)
    store = ComposeProjectStore(target)
    with pytest.raises(ConfigurationError):
        store.load()
    with pytest.raises(ConfigurationError):
        store.save(project(tmp_path))
    assert target.read_text() == text


def test_saved_locations_are_revalidated_and_do_not_store_yaml_contents(tmp_path):
    target = tmp_path / "compose-projects.json"
    selected = project(tmp_path)
    (tmp_path / "local.yaml").write_text("services: {}\n# private-value")
    store = ComposeProjectStore(target)
    store.save(selected)
    assert "private-value" not in target.read_text()
    location = store.load()["catalog"]
    assert location.resolve().fingerprints != selected.fingerprints
    (tmp_path / "compose.yaml").unlink()
    with pytest.raises(ComposeError):
        location.resolve()


def test_atomic_replace_failure_preserves_previous_document(tmp_path, monkeypatch):
    target = tmp_path / "compose-projects.json"
    store = ComposeProjectStore(target)
    store.save(project(tmp_path))
    before = target.read_bytes()

    def denied(*_args):
        raise PermissionError

    monkeypatch.setattr("debugpilot.storage.compose_projects.os.replace", denied)
    with pytest.raises(ConfigurationError):
        store.save(project(tmp_path, "orders"))
    assert target.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_oversized_document_is_rejected_without_overwrite(tmp_path):
    target = tmp_path / "compose-projects.json"
    target.write_bytes(b" " * (256 * 1024 + 1))
    before = target.read_bytes()
    with pytest.raises(ConfigurationError):
        ComposeProjectStore(target).save(project(tmp_path))
    assert target.read_bytes() == before
