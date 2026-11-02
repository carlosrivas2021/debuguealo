import subprocess

import pytest

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.tui import launch_file
from debugpilot.tui.launch_file import open_launch_file as _open_launch_file


def run_editor_success(target, monkeypatch):
    monkeypatch.setattr(launch_file.shutil, "which", lambda _name: "/tools/nano")
    monkeypatch.setattr(
        launch_file.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    _open_launch_file(target)


def test_duplicate_nested_key_is_rejected_without_rewriting_or_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "launch.json"
    original = b'{"custom":{"a":1,"a":2}}'
    target.write_bytes(original)

    with pytest.raises(ConfigurationError, match="duplicate object key"):
        run_editor_success(target, monkeypatch)

    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_nonstandard_number_constant_is_rejected_at_token_location(
    tmp_path, monkeypatch, constant
):
    target = tmp_path / "launch.json"
    original = b'{"custom":' + constant + b"}"
    target.write_bytes(original)

    with pytest.raises(ConfigurationError) as error:
        run_editor_success(target, monkeypatch)

    assert str(error.value) == "Invalid JSON in launch.json at line 1, column 11."
    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]


def test_nonstandard_constant_before_unterminated_string_reports_safe_error(
    tmp_path, monkeypatch
):
    target = tmp_path / "launch.json"
    original = b'{"x":NaN,"s":"unterminated}'
    target.write_bytes(original)

    with pytest.raises(ConfigurationError) as error:
        run_editor_success(target, monkeypatch)

    assert str(error.value) == "Invalid JSON in launch.json at line 1, column 6."
    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]


def test_quoted_nan_is_not_reported_as_a_nonstandard_constant(tmp_path, monkeypatch):
    target = tmp_path / "launch.json"
    target.write_bytes(b'{"custom":"NaN"}')

    run_editor_success(target, monkeypatch)

    assert target.read_bytes() == b'{\n  "custom": "NaN"\n}\n'


def test_escaped_lone_surrogate_is_pretty_printed_without_decoding_loss(tmp_path, monkeypatch):
    target = tmp_path / "launch.json"
    original = b'{"version":1,"configurations":[],"custom":"\\ud800"}'
    target.write_bytes(original)

    run_editor_success(target, monkeypatch)

    assert target.read_bytes() == (
        b'{\n  "version": 1,\n  "configurations": [],\n  "custom": "\\ud800"\n}\n'
    )


def test_decimal_number_token_is_preserved_exactly(tmp_path, monkeypatch):
    target = tmp_path / "launch.json"
    target.write_bytes(b'{"custom":0.1234567890123456789}')

    run_editor_success(target, monkeypatch)

    assert target.read_bytes() == b'{\n  "custom": 0.1234567890123456789\n}\n'


def test_pretty_output_over_launch_store_limit_is_refused_unchanged(tmp_path, monkeypatch):
    target = tmp_path / "launch.json"
    prefix = b'{"version":1,"configurations":[],"custom":"'
    suffix = b'"}'
    original = prefix + b"x" * (262139 - len(prefix) - len(suffix)) + suffix
    assert len(original) == 262139
    target.write_bytes(original)

    with pytest.raises(ConfigurationError, match="256 KiB limit"):
        run_editor_success(target, monkeypatch)

    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]
