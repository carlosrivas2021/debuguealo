"""AWS credential refresh writes only credential keys and never exposes their values."""

import json
import os
import stat
import subprocess

import pytest
from test_tui_compose import Service
from test_tui_grouping import Docker, item, ready, until
from textual.widgets import Static
from typer.testing import CliRunner

import debugpilot.storage.aws_credentials as aws
from debugpilot.cli import app as cli_app
from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.storage.launch_profiles import LaunchProfileStore
from debugpilot.tui.app import DebugPilotApp

SECRET = "SECRETvalue/123+abc="
TOKEN = "TOKENvalue/xyz="


def creds(token=TOKEN, key="AKIANEW"):
    return aws._Credentials(key, SECRET, token, "2026-11-04T20:00:00Z")


def test_render_replaces_only_credential_keys_and_appends_missing():
    original = (
        "AWS_REGION=us-west-1\n"
        "AWS_ACCESS_KEY_ID=old\n"
        "# comment\n"
        "export AWS_SECRET_ACCESS_KEY=old\n"
        "AWS_ACCESS_KEY_ID=duplicate\n"
        "OTHER=keep\n"
    )
    assert aws.render_env_file(original, creds()) == (
        "AWS_REGION=us-west-1\n"
        "AWS_ACCESS_KEY_ID=AKIANEW\n"
        "# comment\n"
        f"AWS_SECRET_ACCESS_KEY={SECRET}\n"
        "OTHER=keep\n"
        f"AWS_SESSION_TOKEN={TOKEN}\n"
    )


def test_render_drops_stale_session_token_when_none_is_issued():
    rendered = aws.render_env_file("AWS_SESSION_TOKEN=stale\nA=1\n", creds(token=None))
    assert "stale" not in rendered and "AWS_SESSION_TOKEN" not in rendered
    assert rendered.startswith("A=1\n")


def test_render_preserves_windows_newlines():
    assert aws.render_env_file("A=1\r\n", creds()).count("\r\n") == 4


def test_write_is_private_and_creates_missing_file(tmp_path):
    path = tmp_path / ".env.aws"
    aws.write_env_file(path, creds())
    assert f"AWS_SECRET_ACCESS_KEY={SECRET}" in path.read_text()
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == [".env.aws"]


def test_write_refuses_symlink(tmp_path):
    real = tmp_path / "real.env"
    real.write_text("A=1\n")
    link = tmp_path / ".env.aws"
    try:
        link.symlink_to(real)
    except OSError:  # Windows accounts without Developer Mode cannot create symlinks.
        pytest.skip("this account cannot create symlinks")
    with pytest.raises(aws.CredentialError, match="symlink"):
        aws.write_env_file(link, creds())
    assert real.read_text() == "A=1\n"


def _completed(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_export_uses_cli_without_shell_and_hides_values(monkeypatch):
    monkeypatch.setattr(aws.shutil, "which", lambda _name: "/bin/aws")
    calls = []
    payload = {
        "Version": 1,
        "AccessKeyId": "AKIANEW",
        "SecretAccessKey": SECRET,
        "SessionToken": TOKEN,
        "Expiration": "2026-11-04T20:00:00+00:00",
    }

    def runner(arguments):
        calls.append(arguments)
        return _completed(stdout=json.dumps(payload))

    result = aws.export_credentials("dev", runner=runner)
    assert calls == [
        ["/bin/aws", "configure", "export-credentials", "--format", "process", "--profile", "dev"]
    ]
    assert result.session_token == TOKEN
    assert SECRET not in repr(result) and TOKEN not in repr(result)


def test_export_failure_suggests_sso_login(monkeypatch):
    monkeypatch.setattr(aws.shutil, "which", lambda _name: "/bin/aws")
    with pytest.raises(aws.CredentialError, match="aws sso login --profile dev"):
        aws.export_credentials(
            "dev", runner=lambda _args: _completed(255, stderr="Error: token expired\n")
        )


@pytest.mark.parametrize("stdout", ["not json", '{"AccessKeyId": "x"}', '{"AccessKeyId":"a b"}'])
def test_export_rejects_unexpected_output(monkeypatch, stdout):
    monkeypatch.setattr(aws.shutil, "which", lambda _name: "/bin/aws")
    with pytest.raises(aws.CredentialError, match="unexpected format"):
        aws.export_credentials(None, runner=lambda _args: _completed(stdout=stdout))


def test_export_requires_aws_cli(monkeypatch):
    monkeypatch.setattr(aws.shutil, "which", lambda _name: None)
    with pytest.raises(aws.CredentialError, match="not installed"):
        aws.export_credentials(None)


def test_refresh_exports_once_per_profile_and_writes_shared_files_once(tmp_path):
    shared = tmp_path / "shared.env"
    other = tmp_path / "other.env"
    exports = []

    def exporter(profile):
        exports.append(profile)
        if profile == "broken":
            raise aws.CredentialError("expired")
        return creds()

    result = aws.refresh_targets(
        [
            ("A", aws.AwsCredentialsTarget((shared,))),
            ("B", aws.AwsCredentialsTarget((shared, other))),
            ("C", aws.AwsCredentialsTarget((other,), "broken")),
        ],
        exporter=exporter,
    )
    assert exports == [None, "broken"]
    assert result.updated_files == [shared, other]
    assert result.profiles == ["A", "B"]
    assert result.errors == ["AWS profile broken: expired"]


def _write_launch(root, aws_credentials):
    (root / "local").mkdir(exist_ok=True)
    (root / "compose.yaml").write_text("services: {}\n")
    store = LaunchProfileStore(root)
    store.path.parent.mkdir(exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "configurations": [
                    {
                        "name": "Scheduler",
                        "type": "docker-compose",
                        "projectName": "scheduler",
                        "cwd": "${workspaceFolder}",
                        "files": ["compose.yaml"],
                        "awsCredentials": aws_credentials,
                    }
                ],
            }
        )
    )
    return store


def test_store_resolves_targets_including_missing_files(tmp_path):
    store = _write_launch(tmp_path, {"envFiles": ["local/.env.aws"], "profile": "dev"})
    ((profile, target),) = store.aws_credential_targets()
    assert profile.pending_reason is None
    assert target == aws.AwsCredentialsTarget((tmp_path / "local" / ".env.aws",), "dev")


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"envFiles": []},
        {"envFiles": "local/.env.aws"},
        {"envFiles": ["local/.env.aws"], "profile": "bad profile"},
        {"envFiles": ["local/.env.aws"], "extra": True},
        {"envFiles": ["../outside.env"]},
        {"envFiles": ["missing-dir/.env.aws"]},
    ],
)
def test_invalid_aws_credentials_leave_profile_pending(tmp_path, value):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    store = _write_launch(workspace, value)
    (profile,) = store.profiles()
    assert profile.pending_reason is not None
    assert store.aws_credential_targets() == []


def test_cli_refresh_reports_files_without_values(tmp_path, monkeypatch):
    store = _write_launch(tmp_path, {"envFiles": ["local/.env.aws"]})
    monkeypatch.setattr("debugpilot.storage.launch_profiles.LaunchProfileStore", lambda: store)
    monkeypatch.setattr(aws, "refresh_targets", lambda targets: _refresh(targets))
    result = CliRunner().invoke(cli_app, ["credentials", "refresh"])
    assert result.exit_code == 0, result.output
    assert "Updated" in result.output and "Scheduler" in result.output
    assert SECRET not in result.output and TOKEN not in result.output
    assert f"AWS_SESSION_TOKEN={TOKEN}" in (tmp_path / "local" / ".env.aws").read_text()


_original_refresh = aws.refresh_targets


def _refresh(targets):
    return _original_refresh(targets, exporter=lambda _profile: creds())


async def test_tui_refresh_offers_recreate_only_for_running_profiles(tmp_path, monkeypatch):
    store = _write_launch(tmp_path, {"envFiles": ["local/.env.aws"]})
    raw = json.loads(store.path.read_text())
    stopped = dict(raw["configurations"][0], name="Idle", projectName="idle")
    raw["configurations"].append(stopped)
    store.path.write_text(json.dumps(raw))
    monkeypatch.setattr(aws, "refresh_targets", lambda targets: _refresh(targets))
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _: service)
    docker = Docker()
    docker.inventory = [item("sched-api", "scheduler", "api")]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(app._launch_profiles) == 2 and ready(app))
        await pilot.press("a")
        await until(pilot, lambda: bool(app._pending_credential_recreates))
        message = str(app.query_one("#inline-compose-message", Static).render())
        assert "Recreate Scheduler" in message and "Idle" not in message
        assert SECRET not in message
        assert not service.runs
        await pilot.click("#inline-compose-confirm")
        await until(pilot, lambda: bool(service.runs))
        ((plan, confirmed),) = service.runs
        assert confirmed and plan.project.project_name == "scheduler"
        assert plan.action == "recreate"


async def test_tui_skip_does_not_recreate(tmp_path, monkeypatch):
    _write_launch(tmp_path, {"envFiles": ["local/.env.aws"]})
    monkeypatch.setattr(aws, "refresh_targets", lambda targets: _refresh(targets))
    service = Service()
    monkeypatch.setattr("debugpilot.docker.compose.ComposeService", lambda _: service)
    docker = Docker()
    docker.inventory = [item("sched-api", "scheduler", "api")]
    app = DebugPilotApp(
        DebugPilotEngine(Settings(), docker=docker), workspace=tmp_path, refresh_interval=0.05
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: bool(app._launch_profiles) and ready(app))
        await pilot.press("a")
        await until(pilot, lambda: bool(app._pending_credential_recreates))
        await pilot.press("escape")
        assert not app._pending_credential_recreates
        assert not app.query_one("#inline-compose").display
        assert not service.runs


async def test_aws_refresh_shortcut_is_inactive_in_code_area(monkeypatch, tmp_path):
    from test_code_debug_ui import debug_app

    app, _roots, _store = debug_app(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(app, "action_refresh_aws_credentials", lambda: calls.append("refresh"))
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.press("a")
        await pilot.pause()
        assert calls == ["refresh"]

        await pilot.click("#area-code")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert calls == ["refresh"], "AWS refresh ran from the Code area"
