"""Loading and saving editor text safely: atomic, mode-preserving, conflict-aware."""

import os
import stat

import pytest

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.text_files import MAX_TEXT_BYTES, load_text, save_text
from debugpilot.tui.launch_file import format_launch_text


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_missing_file_opens_empty_and_is_created_private_on_save(tmp_path):
    target = tmp_path / ".aws" / "credentials"
    loaded = load_text(target)
    assert loaded.text == "" and not loaded.exists

    saved = save_text(loaded, "[default]\naws_access_key_id = X\n")

    assert target.read_text(encoding="utf-8") == "[default]\naws_access_key_id = X\n"
    assert mode(target) == 0o600
    assert mode(target.parent) == 0o700
    assert saved.exists and saved.text == target.read_text(encoding="utf-8")


def test_saving_keeps_the_existing_mode_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "config"
    target.write_text("[default]\n", encoding="utf-8")
    target.chmod(0o640)

    save_text(load_text(target), "[default]\nregion = us-east-1\n")

    assert target.read_text(encoding="utf-8") == "[default]\nregion = us-east-1\n"
    assert mode(target) == 0o640
    assert sorted(path.name for path in tmp_path.iterdir()) == ["config"]


def test_a_file_changed_on_disk_after_opening_is_not_overwritten(tmp_path):
    target = tmp_path / "config"
    target.write_text("old\n", encoding="utf-8")
    loaded = load_text(target)
    target.write_text("newer from elsewhere\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="changed on disk since it was opened"):
        save_text(loaded, "mine\n")

    assert target.read_text(encoding="utf-8") == "newer from elsewhere\n"


def test_a_file_created_after_opening_it_missing_is_not_overwritten(tmp_path):
    target = tmp_path / "credentials"
    loaded = load_text(target)
    target.write_text("created elsewhere\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="changed on disk since it was opened"):
        save_text(loaded, "mine\n")

    assert target.read_text(encoding="utf-8") == "created elsewhere\n"


def test_saving_twice_from_the_returned_state_works(tmp_path):
    target = tmp_path / "config"
    saved = save_text(load_text(target), "one\n")
    save_text(saved, "two\n")
    assert target.read_text(encoding="utf-8") == "two\n"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_symlinked_file_is_written_through_and_the_link_kept(tmp_path):
    real = tmp_path / "dotfiles" / "aws-config"
    real.parent.mkdir()
    real.write_text("old\n", encoding="utf-8")
    link = tmp_path / "config"
    link.symlink_to(real)

    save_text(load_text(link), "new\n")

    assert link.is_symlink()
    assert real.read_text(encoding="utf-8") == "new\n"


def test_text_that_is_not_utf8_or_too_large_is_refused(tmp_path):
    binary = tmp_path / "binary"
    binary.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ConfigurationError, match="not UTF-8 text"):
        load_text(binary)

    large = tmp_path / "large"
    large.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
    with pytest.raises(ConfigurationError, match="larger than"):
        load_text(large)

    with pytest.raises(ConfigurationError, match="larger than"):
        save_text(load_text(tmp_path / "new"), "x" * (MAX_TEXT_BYTES + 1))
    assert not (tmp_path / "new").exists()


def test_a_directory_is_not_opened_as_text(tmp_path):
    with pytest.raises(ConfigurationError, match="not a regular file"):
        load_text(tmp_path)


def test_launch_text_is_formatted_like_after_the_terminal_editor():
    text = '{"version":1,"configurations":[{"name":"Ñandú","z":1,"a":[]}]}'
    assert format_launch_text(text) == (
        '{\n  "version": 1,\n  "configurations": [\n    {\n      "name": "Ñandú",\n'
        '      "z": 1,\n      "a": []\n    }\n  ]\n}\n'
    )


@pytest.mark.parametrize(("text", "position"), [
    ('{\n  "version": 1,\n  "configurations": [\n}', "line 4, column 1"),
    ('{"version": 1, "version": 2}', "line 1, column 1 (duplicate object key)"),
    ('{\n  "version": NaN\n}', "line 2, column 14"),
])
def test_invalid_launch_text_reports_where_without_content(text, position):
    with pytest.raises(ConfigurationError) as error:
        format_launch_text(text)
    assert str(error.value) == f"Invalid JSON in launch.json at {position}."


def test_an_outside_write_with_the_same_size_and_restored_mtime_is_still_detected(tmp_path):
    target = tmp_path / "credentials"
    target.write_text("key = AAAA\n", encoding="utf-8")
    loaded = load_text(target)
    before = target.stat()
    target.write_text("key = BBBB\n", encoding="utf-8")
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))

    with pytest.raises(ConfigurationError, match="changed on disk since it was opened"):
        save_text(loaded, "key = mine\n")

    assert target.read_text(encoding="utf-8") == "key = BBBB\n"


def test_formatted_launch_text_over_the_limit_keeps_the_previous_message():
    prefix = '{"version":1,"configurations":[],"custom":"'
    text = prefix + "x" * (262139 - len(prefix) - 2) + '"}'
    with pytest.raises(ConfigurationError) as error:
        format_launch_text(text)
    assert str(error.value) == (
        "Formatted launch.json exceeds the 256 KiB limit; the original file was left unchanged."
    )
