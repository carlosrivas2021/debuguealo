import json
from pathlib import Path

import pytest

import debugpilot.docker.compose as compose
from debugpilot.docker.compose import ComposeResult, ComposeService
from debugpilot.storage.config import Settings
from debugpilot.storage.launch_profiles import LaunchProfileStore
from debugpilot.tui.app import DebugPilotApp


class _Output:
    def __init__(self, data=b"done\n"):
        self.data = data

    async def read(self, size):
        data, self.data = self.data[:size], self.data[size:]
        return data


class _Process:
    pid = None
    returncode = 0

    def __init__(self, data=b"done\n"):
        self.stdout = _Output(data)

    async def wait(self):
        return self.returncode


def _command(argv):
    index = argv.index("compose") + 1
    while argv[index] in {"--project-directory", "--project-name", "--env-file", "-f"}:
        index += 2
    return argv[index]


def _is_directory(path):
    return path.is_dir()


@pytest.mark.asyncio
async def test_profile_json_reaches_fake_compose_runtime_without_mutating_source(
    tmp_path, monkeypatch
):
    source = tmp_path / "compose.yaml"
    source_bytes = b"services:\n  api:\n    image: example/api\n"
    source.write_bytes(source_bytes)
    env_file = tmp_path / "local.env"
    env_file.write_text("FROM_FILE=still-an-interpolation-input\n")
    overrides = {
        "services": {
            "api": {
                "environment": {"MODE": "literal-$VALUE", "TOKEN": "sensitive-profile-value"},
                "ports": [],
            }
        }
    }
    raw = {
        "type": "docker-compose",
        "projectName": "demo",
        "cwd": "${workspaceFolder}",
        "files": ["compose.yaml"],
        "environmentFiles": ["local.env"],
        "up": {"build": False},
        "overrides": overrides,
    }
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    store.path.write_text(json.dumps({"version": 1, "configurations": [raw]}))
    (profile,) = store.profiles()
    app = object.__new__(DebugPilotApp)
    app._launch_store = store
    project = app._project_from_profile(profile)

    assert project.service_overrides is not None
    assert project.environment_files == (env_file.resolve(),)
    assert project.process_cwd == tmp_path.resolve()
    assert "sensitive-profile-value" not in repr(profile)
    assert "sensitive-profile-value" not in repr(project)
    overrides["services"]["api"]["environment"]["MODE"] = "changed"
    assert "sensitive-profile-value" not in repr(profile)

    override_payloads = []

    async def create(*argv, **kwargs):
        command = _command(argv)
        if command == "config":
            return _Process(b"api\n" if "--services" in argv else b"services: {}\n")
        assert _is_directory(Path(kwargs["env"]["DOCKER_CONFIG"]))
        files = [Path(argv[i + 1]) for i, value in enumerate(argv[:-1]) if value == "-f"]
        assert files[:-1] == [source.resolve()]
        override_payloads.append(files[-1].read_text())
        return _Process()

    monkeypatch.setattr(compose.shutil, "which", lambda _name: "/tools/docker")
    monkeypatch.setattr(compose.asyncio, "create_subprocess_exec", create)
    service = ComposeService(Settings())
    plan = service.preview(project, "recreate")
    result = await service.run(plan, confirmed=True)

    assert result == ComposeResult(0, "done\n")
    assert override_payloads == [
        "services:\n"
        '  "api":\n'
        "    environment:\n"
        '      "MODE": "literal-$$VALUE"\n'
        '      "TOKEN": "sensitive-profile-value"\n'
        "    ports: !override []\n"
    ]
    assert source.read_bytes() == source_bytes


@pytest.mark.parametrize(
    "invalid_overrides",
    [
        {
            "services": {
                "api": {
                    "environment": {"SECRET": "sensitive-invalid-value"},
                    "ports": None,
                }
            }
        },
        {
            "services": {
                "api": {
                    "environment": {"SECRET": "sensitive-invalid-value"},
                    "extra": True,
                }
            }
        },
    ],
)
def test_invalid_profile_overrides_are_pending_and_redacted(tmp_path, invalid_overrides):
    source = tmp_path / "compose.yaml"
    source.write_text("services: {}\n")
    secret = "sensitive-invalid-value"
    raw = {
        "type": "docker-compose",
        "projectName": "demo",
        "cwd": "${workspaceFolder}",
        "files": ["compose.yaml"],
        "overrides": invalid_overrides,
    }
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    original = json.dumps({"version": 1, "configurations": [raw]}).encode()
    store.path.write_bytes(original)
    (profile,) = store.profiles()
    assert profile.pending_reason
    assert secret not in profile.pending_reason
    assert secret not in repr(profile)
    assert store.path.read_bytes() == original
    assert store.resolve(profile) is None


def test_empty_overrides_use_legacy_profile_path_and_repr_redacts_raw(tmp_path):
    source = tmp_path / "compose.yaml"
    source.write_text("services: {}\n")
    raw = {
        "type": "docker-compose",
        "projectName": "demo",
        "cwd": "${workspaceFolder}",
        "files": ["compose.yaml"],
        "overrides": {"services": {}},
    }
    store = LaunchProfileStore(tmp_path)
    store.path.parent.mkdir()
    store.path.write_text(json.dumps({"version": 1, "configurations": [raw]}))
    (profile,) = store.profiles()
    resolved = store.resolve(profile)
    assert resolved is not None
    assert resolved.service_overrides is None
    assert "overrides" not in repr(profile)
    assert "service_overrides" not in repr(resolved)