"""The dashboard learns about newer releases without breaking offline use."""

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from test_code_run_ui import setup_app

from debugpilot import update_check
from debugpilot.update_check import REPOSITORY_URL, UPDATE_COMMAND, available_update

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.delenv(update_check.OPT_OUT_ENV, raising=False)
    return tmp_path / "update-check.json"


def _fetcher(result, calls):
    def fetch():
        calls.append(1)
        if isinstance(result, Exception):
            raise result
        return result

    return fetch


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("0.3.0", "0.2.0", "0.3.0"),
        ("v0.10.0", "0.9.1", "0.10.0"),
        ("0.2.0", "0.2.0", None),
        ("0.1.9", "0.2.0", None),
        ("not-a-version", "0.2.0", None),
    ],
)
def test_reports_only_strictly_newer_releases(cache, latest, current, expected):
    calls = []
    found = available_update(current, now=NOW, fetch=_fetcher(latest, calls), path=cache)
    assert found == expected
    assert calls == [1]


def test_fresh_cache_answers_without_touching_the_network(cache):
    cache.write_text(
        json.dumps({"checked_at": (NOW - timedelta(hours=1)).isoformat(), "latest": "0.3.0"})
    )
    calls = []
    assert available_update("0.2.0", now=NOW, fetch=_fetcher("9.9.9", calls), path=cache) == "0.3.0"
    assert calls == []


def test_stale_cache_fetches_again_and_is_rewritten(cache):
    cache.write_text(
        json.dumps({"checked_at": (NOW - timedelta(days=2)).isoformat(), "latest": "0.3.0"})
    )
    calls = []
    assert available_update("0.2.0", now=NOW, fetch=_fetcher("0.4.0", calls), path=cache) == "0.4.0"
    assert calls == [1]
    assert json.loads(cache.read_text()) == {"checked_at": NOW.isoformat(), "latest": "0.4.0"}


@pytest.mark.parametrize("error", [OSError("offline"), TimeoutError(), ValueError("bad json")])
def test_network_failures_are_silent_and_not_retried_until_the_cache_expires(cache, error):
    calls = []
    assert available_update("0.2.0", now=NOW, fetch=_fetcher(error, calls), path=cache) is None
    assert available_update("0.2.0", now=NOW, fetch=_fetcher(error, calls), path=cache) is None
    assert calls == [1]


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        '{"checked_at": "2026-11-11T11:00:00", "latest": "9.9.9"}',  # naive timestamp
        '{"checked_at": "2026-11-11T11:00:00+00:00", "latest": 7}',
    ],
)
def test_corrupt_cache_is_ignored(cache, content):
    cache.write_text(content)
    calls = []
    assert available_update("0.2.0", now=NOW, fetch=_fetcher("0.3.0", calls), path=cache) == "0.3.0"
    assert calls == [1]


def test_opt_out_and_unknown_versions_skip_the_check(cache, monkeypatch):
    calls = []
    assert (
        available_update("0+unknown", now=NOW, fetch=_fetcher("0.3.0", calls), path=cache) is None
    )
    monkeypatch.setenv(update_check.OPT_OUT_ENV, "1")
    assert available_update("0.2.0", now=NOW, fetch=_fetcher("0.3.0", calls), path=cache) is None
    assert calls == []
    assert not cache.exists()


def test_latest_tag_picks_the_highest_release_tag():
    output = "\n".join(
        [
            "aaa\trefs/tags/v0.2.0",
            "bbb\trefs/tags/v0.10.1",
            "ccc\trefs/tags/v0.9.0",
            "ddd\trefs/tags/nightly",
            "eee\trefs/heads/v9.9.9",
            "",
        ]
    )
    assert update_check.latest_tag(output) == "v0.10.1"
    assert update_check.latest_tag("") is None
    assert update_check.latest_tag("fff\trefs/tags/nightly") is None


def test_fetch_reads_tags_with_git_and_never_prompts(monkeypatch):
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="abc\trefs/tags/v0.3.0\n")

    monkeypatch.setattr(update_check.subprocess, "run", run)
    assert update_check.fetch_latest_version() == "v0.3.0"
    assert seen["command"] == ["git", "ls-remote", "--tags", "--refs", REPOSITORY_URL]
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert seen["env"]["GCM_INTERACTIVE"] == "never"
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["timeout"] == update_check.TIMEOUT_SECONDS
    assert seen["check"] is True


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("git"),
        subprocess.TimeoutExpired(["git"], 5),
        subprocess.CalledProcessError(128, ["git"], stderr="Authentication failed"),
    ],
)
def test_git_failures_mean_no_update_notice(cache, monkeypatch, error):
    def run(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(update_check.subprocess, "run", run)
    assert available_update("0.2.0", now=NOW, path=cache) is None


async def test_dashboard_announces_an_available_update(monkeypatch, tmp_path):
    monkeypatch.setattr(update_check, "available_update", lambda: "0.3.0")
    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        messages = [item.message for item in app._notifications]
    assert any(
        "debugealo 0.3.0 is available" in message and UPDATE_COMMAND in message
        for message in messages
    )


async def test_dashboard_stays_quiet_when_up_to_date(monkeypatch, tmp_path):
    monkeypatch.setattr(update_check, "available_update", lambda: None)
    app = setup_app(monkeypatch, tmp_path, "print('hi')")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        messages = [item.message for item in app._notifications]
    assert not any("is available" in message for message in messages)
