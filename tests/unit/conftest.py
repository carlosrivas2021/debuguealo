
import pytest


@pytest.fixture(autouse=True)
def isolate_compose_project_configuration(tmp_path, monkeypatch, request):
    monkeypatch.setattr(
        "debugpilot.storage.compose_projects.projects_path",
        lambda: tmp_path / "user-settings" / "compose-projects.json",
    )
    monkeypatch.setattr(
        "debugpilot.storage.launch_profiles.config_path",
        lambda: tmp_path / ".debugpilot" / "config.toml",
    )

    monkeypatch.setattr(
        "debugpilot.storage.code_projects.config_path",
        lambda: tmp_path / ".debugpilot" / "config.toml",
    )
    monkeypatch.setattr(
        "debugpilot.storage.breakpoints.config_path",
        lambda: tmp_path / ".debugpilot" / "config.toml",
    )
    monkeypatch.setattr(
        "debugpilot.storage.watches.config_path",
        lambda: tmp_path / ".debugpilot" / "config.toml",
    )

    # Both central defaults remain isolated under this test's temporary root.

