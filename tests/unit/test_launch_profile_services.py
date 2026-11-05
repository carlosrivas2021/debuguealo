"""Launch profiles may restrict Compose actions to an explicit list of services."""

import json
from pathlib import Path

import pytest

import debugpilot.docker.compose as compose
from debugpilot.docker.compose import ComposeError, ComposeProject, ComposeResult, ComposeService
from debugpilot.storage.config import Settings
from debugpilot.storage.launch_profiles import LaunchProfileStore, profile_services


class _Output:
    def __init__(self, data):
        self.data = data

    async def read(self, size):
        data, self.data = self.data[:size], self.data[size:]
        return data


class _Process:
    pid = None
    returncode = 0

    def __init__(self, data=b"started\n"):
        self.stdout = _Output(data)

    async def wait(self):
        return self.returncode


def _command(argv):
    index = argv.index("compose") + 1
    while argv[index] in {"--project-directory", "--project-name", "--env-file", "-f"}:
        index += 2
    return argv[index]


def _write_profile(root: Path, **extra) -> LaunchProfileStore:
    (root / "compose.yaml").write_text("services:\n  database: {}\n  worker: {}\n")
    store = LaunchProfileStore(root)
    store.path.parent.mkdir()
    profile = {
        "name": "Platform",
        "type": "docker-compose",
        "projectName": "platform",
        "cwd": "${workspaceFolder}",
        "files": ["compose.yaml"],
        **extra,
    }
    store.path.write_text(json.dumps({"version": 1, "configurations": [profile]}))
    return store


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ()),
        (["database"], ("database",)),
        (["database", "worker-api"], ("database", "worker-api")),
        ([], ()),
        ("database", None),
        (["database", "database"], None),
        (["--no-deps"], None),
        (["a b"], None),
        ([1], None),
    ],
)
def test_profile_services_validation(value, expected):
    raw = {} if value is None else {"services": value}
    assert profile_services(raw) == expected


def test_store_resolves_services_and_marks_invalid_lists_pending(tmp_path):
    store = _write_profile(tmp_path, services=["database"])
    (profile,) = store.profiles("platform")
    assert profile.pending_reason is None
    assert store.resolve(profile).services == ("database",)

    profile.raw["services"] = []
    assert store.resolve(profile).services == ()

    profile.raw["services"] = "database"
    assert store.resolve(profile) is None


def test_store_reports_specific_pending_reason(tmp_path):
    store = _write_profile(tmp_path, services=["--force"])
    (profile,) = store.profiles("platform")
    assert profile.pending_reason is not None
    assert "services" in profile.pending_reason


def test_profiles_without_services_keep_previous_behavior(tmp_path):
    store = _write_profile(tmp_path)
    (profile,) = store.profiles("platform")
    assert store.resolve(profile).services == ()


@pytest.fixture
def docker(monkeypatch):
    monkeypatch.setattr(compose.shutil, "which", lambda _name: "/tools/docker")
    calls = []
    known = [b"database\nworker\n"]

    async def create(*argv, **_kwargs):
        calls.append(argv)
        if _command(argv) == "config":
            return _Process(known[0])
        return _Process()

    monkeypatch.setattr(compose.asyncio, "create_subprocess_exec", create)
    return calls, known


def test_compose_project_rejects_invalid_services(tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    for services in (("-d",), ("a", "a"), ("ok", 3)):
        with pytest.raises(ComposeError, match="services"):
            ComposeProject.create(tmp_path, ("compose.yaml",), "demo", services=services)


@pytest.mark.parametrize("action", ["recreate", "rebuild", "restart"])
def test_plan_appends_profile_services_without_no_deps(tmp_path, docker, action):
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    project = ComposeProject.create(tmp_path, ("compose.yaml",), "platform", services=("database",))
    plan = ComposeService(Settings()).preview(project, action)
    arguments = plan._arguments("<cfg>")
    assert arguments[-1] == "database"
    assert "--no-deps" not in arguments
    assert plan.scope == "database"
    assert plan.display.endswith("database")


def test_explicit_service_target_wins_over_profile_services(tmp_path, docker):
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    project = ComposeProject.create(
        tmp_path, ("compose.yaml",), "platform", services=("database", "worker")
    )
    plan = ComposeService(Settings()).preview(project, "recreate", "worker")
    assert plan._arguments("<cfg>")[-2:] == ("--no-deps", "worker")
    assert plan.scope == "worker"


def test_without_services_scope_is_all_services(tmp_path, docker):
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    project = ComposeProject.create(tmp_path, ("compose.yaml",), "platform")
    plan = ComposeService(Settings()).preview(project, "recreate")
    assert plan._arguments("<cfg>")[-2:] == ("--pull", "never")
    assert plan.scope == "all services"


async def test_run_verifies_services_before_mutating(tmp_path, docker):
    calls, _known = docker
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    project = ComposeProject.create(tmp_path, ("compose.yaml",), "platform", services=("database",))
    service = ComposeService(Settings())
    result = await service.run(service.preview(project, "recreate"), confirmed=True)
    assert result == ComposeResult(0, "started\n")
    assert [_command(argv) for argv in calls] == ["config", "up"]
    assert "--services" in calls[0]
    assert calls[1][-1] == "database"


async def test_unknown_profile_service_fails_before_mutating(tmp_path, docker):
    calls, known = docker
    known[0] = b"worker\n"
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    project = ComposeProject.create(tmp_path, ("compose.yaml",), "platform", services=("database",))
    service = ComposeService(Settings())
    with pytest.raises(ComposeError, match="database"):
        await service.run(service.preview(project, "recreate"), confirmed=True)
    assert [_command(argv) for argv in calls] == ["config"]


async def test_compose_receives_ssh_agent_socket_but_not_other_variables(
    tmp_path, docker, monkeypatch
):
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "never-forwarded")
    environments = []

    async def create(*argv, **kwargs):
        environments.append(kwargs["env"])
        return _Process()

    monkeypatch.setattr(compose.asyncio, "create_subprocess_exec", create)
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    project = ComposeProject.create(tmp_path, ("compose.yaml",), "platform")
    service = ComposeService(Settings())
    await service.run(service.preview(project, "rebuild"), confirmed=True)
    (environment,) = environments
    assert environment["SSH_AUTH_SOCK"] == "/tmp/agent.sock"
    assert "AWS_SECRET_ACCESS_KEY" not in environment
