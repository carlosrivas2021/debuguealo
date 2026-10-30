import pytest


@pytest.fixture(autouse=True)
def isolate_compose_project_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "debugpilot.storage.compose_projects.projects_path",
        lambda: tmp_path / "user-settings" / "compose-projects.json",
    )
    monkeypatch.setattr("debugpilot.storage.launch_profiles.default_workspace", lambda: tmp_path)
