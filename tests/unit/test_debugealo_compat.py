import importlib
import os
import subprocess
import sys

from typer.testing import CliRunner


def test_new_and_legacy_cli_names_share_expected_version_and_help():
    new_app = importlib.import_module("debugealo.cli").app
    old_app = importlib.import_module("debugpilot.cli").app
    runner = CliRunner()
    new_version = runner.invoke(new_app, ["version"])
    old_version = runner.invoke(old_app, ["version"])
    assert new_version.exit_code == old_version.exit_code == 0
    assert new_version.output.strip() == "debugealo 0.1.0"
    assert old_version.output.strip() == "debugealo 0.1.0"
    for app in (new_app, old_app):
        help_result = runner.invoke(app, ["--help"])
        assert help_result.exit_code == 0
        assert "debugealo" in help_result.output


def test_debugealo_compatibility_imports_keep_one_module_and_class_identity():
    for order in (
        "import debugealo.storage.config; import debugpilot.storage.config",
        "import debugpilot.storage.config; import debugealo.storage.config",
    ):
        script = f"""
import importlib
{order}
new_config = importlib.import_module('debugealo.storage.config')
old_config = importlib.import_module('debugpilot.storage.config')
new_errors = importlib.import_module('debugealo.core.exceptions')
old_errors = importlib.import_module('debugpilot.core.exceptions')
new_models = importlib.import_module('debugealo.core.models')
old_models = importlib.import_module('debugpilot.core.models')
assert new_config is old_config
assert new_errors is old_errors
assert new_models is old_models
from debugealo.storage.config import Settings
from debugpilot.storage.config import Settings as LegacySettings
from debugealo.core.exceptions import ConfigurationError
from debugpilot.core.exceptions import ConfigurationError as LegacyError
assert Settings is LegacySettings
assert ConfigurationError is LegacyError
assert debugealo.__version__ == debugpilot.__version__ == '0.1.0'
"""
        result = subprocess.run([sys.executable, "-c", script], text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""


def test_python_module_entry_points_preserve_old_alias_and_expose_new_name():
    env = os.environ.copy()
    for module in ("debugealo", "debugpilot"):
        result = subprocess.run(
            [sys.executable, "-m", module, "version"],
            text=True,
            capture_output=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "debugealo 0.1.0"


def test_config_and_workspace_storage_keep_legacy_paths_without_writing(tmp_path, monkeypatch):
    from debugpilot.storage import breakpoints, config
    from debugpilot.storage.breakpoints import BreakpointStore
    from debugpilot.storage.launch_profiles import LaunchProfileStore

    target = tmp_path / ".config" / "debugpilot" / "config.toml"
    config_dirs = []

    def legacy_config_dir(*args, **kwargs):
        config_dirs.append((args, kwargs))
        return target.parent

    monkeypatch.setattr(config, "user_config_path", legacy_config_dir)
    monkeypatch.setattr(breakpoints, "config_path", lambda: target)
    assert config.config_path() == target
    assert config_dirs == [(('debugpilot',), {'appauthor': False})]
    assert not target.exists()
    assert config.load_settings() == config.Settings()
    assert not target.exists()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert LaunchProfileStore(workspace).path == workspace / ".debugpilot" / "launch.json"
    assert BreakpointStore().path == target.parent / "projects" / "breakpoints.json"
    assert not (workspace / ".debugpilot" / "launch.json").exists()
    assert not (target.parent / "projects" / "breakpoints.json").exists()


def test_new_package_exports_legacy_cli_and_application_classes():
    assert importlib.import_module("debugealo.cli").app is importlib.import_module(
        "debugpilot.cli"
    ).app
    new_app = importlib.import_module("debugealo.tui.app").DebugPilotApp
    old_app = importlib.import_module("debugpilot.tui.app").DebugPilotApp
    assert new_app is old_app
    assert new_app.TITLE == "debugealo"
