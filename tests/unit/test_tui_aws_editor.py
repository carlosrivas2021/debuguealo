"""Shift+A edits the AWS config and credentials files side by side in Containers."""

import os

import pytest
from test_tui_grouping import Docker, until
from textual.widgets import TextArea

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.aws_credentials import aws_file_paths
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp
from debugpilot.tui.file_editor import FileEditorScreen


@pytest.fixture
def aws_home(tmp_path, monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_FILE", raising=False)
    monkeypatch.delenv("AWS_SHARED_CREDENTIALS_FILE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    return tmp_path / "home" / ".aws"


def test_default_paths_are_in_the_home_aws_folder(aws_home):
    assert aws_file_paths() == (aws_home / "config", aws_home / "credentials")


def test_environment_overrides_are_honored(aws_home, tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "custom-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "~/secrets/creds")
    assert aws_file_paths() == (tmp_path / "custom-config", aws_home.parent / "secrets" / "creds")


def _app(tmp_path):
    return DebugPilotApp(
        DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path, refresh_interval=0.05
    )


async def test_shift_a_opens_config_and_credentials_side_by_side(aws_home, tmp_path):
    aws_home.mkdir(parents=True)
    (aws_home / "config").write_bytes(b"[default]\nregion = us-east-1\n")
    app = _app(tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        await pilot.press("A")
        await until(pilot, lambda: isinstance(app.screen, FileEditorScreen))

        editor = app.screen
        assert [file.label for file in editor.files] == ["AWS config", "AWS credentials"]
        assert [file.loaded.path for file in editor.files] == [
            (aws_home / "config").resolve(), (aws_home / "credentials").resolve()]
        left, right = editor.query(TextArea)
        assert left.text == "[default]\nregion = us-east-1\n" and right.text == ""
        assert left.region.y == right.region.y and left.region.x < right.region.x

        right.insert("[default]\naws_access_key_id = X\n")
        await pilot.press("ctrl+s")
        await pilot.press("escape")
        await until(pilot, lambda: not isinstance(app.screen, FileEditorScreen))
        credentials = aws_home / "credentials"
        assert credentials.read_text(encoding="utf-8") == "[default]\naws_access_key_id = X\n"
        if os.name != "nt":  # Windows has no POSIX permission bits.
            assert credentials.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("focus", ["#code-projects", "#source-text"])
async def test_shift_a_also_opens_the_aws_files_from_the_code_area(aws_home, tmp_path, focus):
    app = _app(tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await until(pilot, lambda: app._inventory_loaded)
        await pilot.click("#area-code")
        app.query_one(focus).focus()
        await pilot.pause()
        await pilot.press("A")
        await until(pilot, lambda: isinstance(app.screen, FileEditorScreen))
        assert [file.label for file in app.screen.files] == ["AWS config", "AWS credentials"]
        await pilot.press("escape")
        await until(pilot, lambda: not isinstance(app.screen, FileEditorScreen))
        assert app.query_one("#code-workspace").display


async def test_typing_a_capital_a_in_the_log_filter_types_it(aws_home):
    from test_tui_detail_cards import Fleet, start
    from test_tui_grouping import ready, select_key
    from textual.widgets import Input

    app = start(Fleet())
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, "container:shop-web")
        await pilot.press("ctrl+l")
        field = app.query_one("#filter-logs", Input)
        field.focus()
        await pilot.pause()
        await pilot.press("A")
        await pilot.pause()
        assert field.value == "A"
        assert not isinstance(app.screen, FileEditorScreen)


async def test_a_live_code_terminal_receives_a_capital_a(aws_home, monkeypatch, tmp_path):
    from test_code_run_ui import setup_app

    app = setup_app(monkeypatch, tmp_path, "print('READY', flush=True); input()")
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("f5")
        terminal = app.query_one("#code-terminal")
        await until(pilot, lambda: "READY" in terminal.render().plain)
        terminal.focus()
        await pilot.pause()
        sent = []
        monkeypatch.setattr(terminal._session, "write", sent.append)
        await pilot.press("A")
        await pilot.pause()
        assert sent == ["A"]
        assert not isinstance(app.screen, FileEditorScreen)
        await pilot.click("#code-stop")
