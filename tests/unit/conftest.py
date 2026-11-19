
import pytest
from textual.widgets import Button


@pytest.fixture(autouse=True)
def immediate_button_presses(monkeypatch):
    # After a press, a Button ignores clicks until a 0.2 s timer ends its "-active" look.
    # A loaded machine runs that timer late, so a test's next click on the same button
    # was dropped at random. People never click twice in 0.2 s expecting two actions.
    monkeypatch.setattr(Button, "_start_active_affect", lambda self: None)


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
    monkeypatch.setattr(
        "debugpilot.storage.exception_modes.config_path",
        lambda: tmp_path / ".debugpilot" / "config.toml",
    )
    monkeypatch.setattr(
        "debugpilot.storage.ui_theme.config_path",
        lambda: tmp_path / ".debugpilot" / "config.toml",
    )

    # Both central defaults remain isolated under this test's temporary root.

