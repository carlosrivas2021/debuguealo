"""Per-profile environment: `env` and `envFile` for Run and Debug, never for attach."""

import asyncio
import json
import sys

import pytest
from test_breakpoint_options_debug import SESSIONS, next_event, program
from test_code_project_store import configure
from test_tui_grouping import Docker, until

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.code_projects import parse_env_file, profile_environment
from debugpilot.storage.config import Settings
from debugpilot.tui.app import DebugPilotApp


def write_profiles(monkeypatch, tmp_path, **fields):
    store = configure(monkeypatch, tmp_path)
    entry = {'name': 'Sample', 'workspaceFolder': str(tmp_path),
             'command': [sys.executable, 'main.py'], **fields}
    store.path.write_text(json.dumps({'version': 1, 'configurations': [entry]}))
    return store


def test_env_and_env_file_merge_over_the_inherited_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('INHERITED', 'kept')
    monkeypatch.setenv('SHARED', 'from-shell')
    (tmp_path / '.env').write_text('SHARED=from-file\nFILE_ONLY=yes\nOVERRIDE=file\n')
    store = write_profiles(monkeypatch, tmp_path, env={'OVERRIDE': 'env', 'EMPTY': ''},
                           envFile='.env')
    profile = store.profiles()[0]
    environment = profile_environment(profile)
    assert environment['INHERITED'] == 'kept'
    assert environment['SHARED'] == 'from-file'
    assert environment['FILE_ONLY'] == 'yes'
    # `env` wins over `envFile`, which wins over the inherited environment.
    assert environment['OVERRIDE'] == 'env'
    assert environment['EMPTY'] == ''


def test_profiles_without_env_inherit_the_environment_unchanged(monkeypatch, tmp_path):
    store = write_profiles(monkeypatch, tmp_path)
    assert profile_environment(store.profiles()[0]) is None


@pytest.mark.parametrize('fields', [
    {'env': ['A=1']},
    {'env': {'1A': 'x'}},
    {'env': {'A-B': 'x'}},
    {'env': {'A': 1}},
    {'env': {'A': 'x\u0000y'}},
    {'envFile': '/etc/environment'},
    {'envFile': '../outside.env'},
    {'envFile': 3},
], ids=['not-a-map', 'leading-digit', 'dash', 'not-text', 'nul', 'absolute', 'parent',
        'not-a-path'])
def test_invalid_env_settings_are_rejected(monkeypatch, tmp_path, fields):
    store = write_profiles(monkeypatch, tmp_path, **fields)
    with pytest.raises(ConfigurationError):
        store.profiles()


def test_attach_profiles_reject_env(monkeypatch, tmp_path):
    store = write_profiles(monkeypatch, tmp_path, env={'A': '1'}, goAttach={
        'host': '127.0.0.1', 'port': 2345, 'remoteRoot': '/app'})
    with pytest.raises(ConfigurationError, match='attach'):
        store.profiles()


def test_env_file_format():
    text = ('# comment\n\nexport API_URL=http://localhost:8000\nQUOTED="a b # not a comment"\n'
            "SINGLE='x=y'\n  SPACED  =  value  \nURL=postgres://u:p@h/db?a=1\n")
    assert parse_env_file(text) == {
        'API_URL': 'http://localhost:8000', 'QUOTED': 'a b # not a comment',
        'SINGLE': 'x=y', 'SPACED': 'value', 'URL': 'postgres://u:p@h/db?a=1'}


@pytest.mark.parametrize(('text', 'line'), [
    ('A=1\nNOEQUALS\n', 2),
    ('1A=x\n', 1),
    ('A="unterminated\n', 1),
], ids=['no-equals', 'bad-name', 'open-quote'])
def test_invalid_env_file_lines_name_the_line_but_not_the_value(text, line):
    with pytest.raises(ConfigurationError) as raised:
        parse_env_file(text)
    assert f'line {line}' in str(raised.value)
    assert 'unterminated' not in str(raised.value)


def test_missing_env_file_is_reported_when_running(monkeypatch, tmp_path):
    store = write_profiles(monkeypatch, tmp_path, envFile='missing.env')
    with pytest.raises(ConfigurationError, match='missing.env'):
        profile_environment(store.profiles()[0])


async def test_run_passes_the_profile_environment(monkeypatch, tmp_path):
    (tmp_path / '.env').write_text('FROM_FILE=file-value\n')
    script = "import os; print('GOT', os.environ['FROM_ENV'], os.environ['FROM_FILE'], flush=True)"
    store = configure(monkeypatch, tmp_path)
    store.path.write_text(json.dumps({'version': 1, 'configurations': [{
        'name': 'Sample', 'workspaceFolder': str(tmp_path),
        'command': [sys.executable, '-u', '-c', script],
        'env': {'FROM_ENV': 'env-value'}, 'envFile': '.env'}]}))
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('f5')
        pane = app.query_one('#code-terminal')
        await until(pilot, lambda: 'GOT env-value file-value' in pane.render().plain)


async def test_run_reports_a_missing_env_file_without_starting(monkeypatch, tmp_path):
    store = configure(monkeypatch, tmp_path)
    marker = tmp_path / 'started'
    store.path.write_text(json.dumps({'version': 1, 'configurations': [{
        'name': 'Sample', 'workspaceFolder': str(tmp_path),
        'command': [sys.executable, '-c', f"open({str(marker)!r}, 'w')"],
        'envFile': 'missing.env'}]}))
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), workspace=tmp_path)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('f5')
        await until(pilot, lambda: 'missing.env' in str(app.query_one('#code-run-state').render()))
        await asyncio.sleep(0.3)
        assert not marker.exists()


PRINT_ENV = {
    'python': ('main.py', 'import os\nprint("GOT", os.environ["DEBUG_VAR"], flush=True)\n'),
    'go': ('main.go', 'package main\n\nimport (\n\t"fmt"\n\t"os"\n)\n\nfunc main() {\n'
           '\tfmt.Println("GOT", os.Getenv("DEBUG_VAR"))\n}\n'),
    'node': ('main.js', 'console.log("GOT", process.env.DEBUG_VAR);\n'),
}


@pytest.mark.parametrize('language', ['python', 'go', 'node'])
async def test_debug_passes_the_profile_environment(tmp_path, language):
    from dataclasses import replace

    profile, _, _ = program(tmp_path, language)
    name, text = PRINT_ENV[language]
    (tmp_path / name).write_text(text)
    profile = replace(profile, env=(('DEBUG_VAR', 'debug-value'),))
    output = []
    session = SESSIONS[language](on_output=lambda category, text: output.append(text))
    try:
        await session.start(profile, {})
        event, _ = await next_event(session, 'terminated', 'stopped')
        assert event == 'terminated'
        assert 'GOT debug-value' in ''.join(output)
    finally:
        await session.close()
