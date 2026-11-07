import hashlib
import importlib
import json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return digest(path)


def test_legacy_saved_data_survives_debugealo_reads_and_interoperable_writes(
    tmp_path, monkeypatch
):
    from debugealo.core.exceptions import ConfigurationError

    config = importlib.import_module("debugealo.storage.config")
    old_config = importlib.import_module("debugpilot.storage.config")
    new_launch = importlib.import_module("debugealo.storage.launch_profiles")
    old_launch = importlib.import_module("debugpilot.storage.launch_profiles")
    new_code = importlib.import_module("debugealo.storage.code_projects")
    old_code = importlib.import_module("debugpilot.storage.code_projects")
    new_breakpoints = importlib.import_module("debugealo.storage.breakpoints")
    old_breakpoints = importlib.import_module("debugpilot.storage.breakpoints")

    assert config is old_config
    assert new_launch is old_launch
    assert new_code is old_code
    assert new_breakpoints is old_breakpoints

    config_root = tmp_path / "config"
    config_root.mkdir()
    monkeypatch.setattr(config, "user_config_path", lambda *_args, **_kwargs: config_root)
    settings_file = config.config_path()
    settings_file.write_text("event_queue_size = 321\ndocker_timeout_seconds = 4\n")
    monkeypatch.setattr(new_launch, "config_path", lambda: settings_file)
    monkeypatch.setattr(new_code, "config_path", lambda: settings_file)
    monkeypatch.setattr(new_breakpoints, "config_path", lambda: settings_file)
    settings_hash = digest(settings_file)

    project_workspace = tmp_path / "compose-workspace"
    project_workspace.mkdir()
    compose_file = project_workspace / "compose.yaml"
    compose_file.write_text("services: {}\n")
    profile = {
        "name": "Saved profile",
        "type": "docker-compose",
        "projectName": "saved-profile",
        "workspaceFolder": str(project_workspace),
        "cwd": "${workspaceFolder}",
        "files": ["compose.yaml"],
        "custom": {"keep": True},
    }
    central_launch_file = config_root / "launch.json"
    local_launch_file = project_workspace / ".debugpilot" / "launch.json"
    central_launch_hash = write_json(
        central_launch_file, {"version": 1, "configurations": [profile]}
    )
    local_launch_hash = write_json(
        local_launch_file, {"version": 1, "configurations": [profile]}
    )

    code_workspace = tmp_path / "code-workspace"
    code_workspace.mkdir()
    code_file = config_root / "projects" / "launch.json"
    code_profile = {
        "name": "Saved code profile",
        "workspaceFolder": str(code_workspace),
        "command": ["python", "main.py"],
        "custom": "preserved",
    }
    code_hash = write_json(code_file, {"version": 1, "configurations": [code_profile]})

    source_root = code_workspace / "src"
    source_root.mkdir()
    source_file = source_root / "main.py"
    source_file.write_text("print('saved')\n")
    breakpoint_file = config_root / "projects" / "breakpoints.json"
    breakpoint_hash = write_json(
        breakpoint_file,
        {
            "version": 1,
            "breakpoints": [
                {"root": str(code_workspace), "file": str(source_file), "lines": [2, 5]}
            ],
        },
    )

    assert config.load_settings().event_queue_size == 321
    assert old_config.load_settings().event_queue_size == 321
    assert [item.name for item in new_launch.LaunchProfileStore().profiles()] == [
        "Saved profile"
    ]
    assert [item.name for item in old_launch.LaunchProfileStore(project_workspace).profiles()] == [
        "Saved profile"
    ]
    assert [item.name for item in new_code.CodeProjectStore().profiles()] == [
        "Saved code profile"
    ]
    assert [item.name for item in old_code.CodeProjectStore().profiles()] == [
        "Saved code profile"
    ]
    marks = {(code_workspace.resolve(), source_file.resolve()): (2, 5)}
    assert new_breakpoints.BreakpointStore().load() == marks
    assert old_breakpoints.BreakpointStore().load() == marks
    assert {
        settings_file: digest(settings_file),
        central_launch_file: digest(central_launch_file),
        local_launch_file: digest(local_launch_file),
        code_file: digest(code_file),
        breakpoint_file: digest(breakpoint_file),
    } == {
        settings_file: settings_hash,
        central_launch_file: central_launch_hash,
        local_launch_file: local_launch_hash,
        code_file: code_hash,
        breakpoint_file: breakpoint_hash,
    }

    writer_workspace = tmp_path / "new-profile-workspace"
    writer_workspace.mkdir()
    (writer_workspace / "compose.yaml").write_text("services: {}\n")
    new_launch.LaunchProfileStore(writer_workspace).save_configuration(
        {
            "name": "Written by debugealo",
            "type": "docker-compose",
            "projectName": "written-profile",
            "cwd": "${workspaceFolder}",
            "files": ["compose.yaml"],
        }
    )
    assert old_launch.LaunchProfileStore(writer_workspace).profiles()[0].name == (
        "Written by debugealo"
    )

    updated_marks = {(code_workspace.resolve(), source_file.resolve()): {3, 7}}
    new_breakpoints.BreakpointStore(breakpoint_file).save(updated_marks)
    assert old_breakpoints.BreakpointStore(breakpoint_file).load() == {
        (code_workspace.resolve(), source_file.resolve()): (3, 7)
    }

    malformed = b'{"version":1,"breakpoints":[{"root":"bad"}]}\n'
    breakpoint_file.write_bytes(malformed)
    before = digest(breakpoint_file)
    try:
        new_breakpoints.BreakpointStore(breakpoint_file).save(updated_marks)
    except ConfigurationError as error:
        assert str(error) == (
            "Invalid Code breakpoints; repair projects/breakpoints.json. "
            "The existing file was not changed."
        )
    else:
        raise AssertionError("saving over malformed legacy breakpoints should fail")
    assert breakpoint_file.read_bytes() == malformed
    assert digest(breakpoint_file) == before
