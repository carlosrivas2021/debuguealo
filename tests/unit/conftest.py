from contextlib import nullcontext

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

    # Both central defaults remain isolated under this test's temporary root.

    # Headless drivers cannot suspend a real terminal; the welcome test asserts
    # ownership and restoration explicitly with its own suspend context.
    monkeypatch.setattr("debugpilot.tui.app.DebugPilotApp.suspend", lambda _app: nullcontext())

    # UI tests must never launch a real system editor. Individual opener tests
    # patch subprocess calls directly and still exercise the real helper.
    if request.node.path.name != "test_launch_file.py":
        monkeypatch.setattr("debugpilot.tui.launch_file.open_launch_file", lambda _path: None)
