import json

import pytest

import debugpilot.docker.compose as compose
from debugpilot.docker.compose import ComposeError, ComposeProject, ComposeResult, ComposeService
from debugpilot.storage.config import Settings


def compose_command(arguments):
    index = arguments.index("compose") + 1
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"--project-directory", "--project-name", "--env-file", "-f"}:
            index += 2
            continue
        return argument
    raise AssertionError("Compose command is missing")


def mutating_calls(calls):
    return [call for call in calls if compose_command(call[1]) != "config"]


@pytest.fixture
def retry_target(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text(
        "services: {api: {image: 'alpine:${TAG:-3.22}', env_file: runtime.env}}\n"
    )
    (tmp_path / "runtime.env").write_text("MODE=old\n")
    (tmp_path / ".env").write_text("TAG=old\n")
    monkeypatch.setattr(compose.shutil, "which", lambda _name: "/tools/docker")
    project = ComposeProject.create(tmp_path, ("compose.yaml",), "orders")
    service = ComposeService(Settings())
    calls = []

    async def run_process(target, arguments, *, on_output=None):
        argv = arguments("private")
        calls.append((target, argv, on_output))
        if compose_command(argv) == "config":
            return ComposeResult(0, json.dumps({"services": {"api": {}}}))
        return ComposeResult(0, "done")

    service._run_process = run_process
    return project, service, calls


@pytest.mark.parametrize("changed", ["dotenv", "env_file"])
async def test_retry_rejects_changed_effective_environment(retry_target, changed):
    project, service, calls = retry_target
    plan = service.preview(project, "rebuild")
    fingerprint = await service.capture_retry_environment(plan)
    path = project.workspace / (".env" if changed == "dotenv" else "runtime.env")
    path.write_text("TAG=changed\n" if changed == "dotenv" else "MODE=changed\n")

    with pytest.raises(ComposeError, match="environment changed"):
        await service.run(plan, confirmed=True, pull_missing=True, retry_fingerprint=fingerprint)
    assert not mutating_calls(calls)


async def test_retry_requires_nonempty_current_fingerprint(retry_target):
    project, service, calls = retry_target
    plan = service.preview(project, "rebuild")
    for fingerprint in (None, ""):
        with pytest.raises(ComposeError, match="fingerprint"):
            await service.run(
                plan, confirmed=True, pull_missing=True, retry_fingerprint=fingerprint
            )
    with pytest.raises(ComposeError, match="environment changed"):
        await service.run(plan, confirmed=True, pull_missing=True, retry_fingerprint="0" * 64)
    assert not mutating_calls(calls)


def make_extends_target(tmp_path, monkeypatch, *, config_result=None):
    workspace = tmp_path / "local"
    agent = workspace / "agente"
    agent.mkdir(parents=True)
    (agent / "docker-compose.yaml").write_text(
        "services:\n  agent:\n    extends:\n      file: ../docker-compose.base.yaml\n"
        "      service: agent\n"
    )
    base_file = workspace / "docker-compose.base.yaml"
    base_file.write_text("services:\n  agent:\n    image: alpine:3.22\n    env_file: [./.env]\n")
    inherited_env = workspace / ".env"
    inherited_env.write_text("MODE=unchanged\n")
    (agent / ".env").write_text("LOCAL=unchanged\n")
    monkeypatch.setattr(compose.shutil, "which", lambda _name: "/tools/docker")
    project = ComposeProject.create(
        workspace,
        ("agente/docker-compose.yaml",),
        "agente",
        project_directory=agent,
        process_cwd=agent,
    )
    service = ComposeService(Settings())
    calls = []

    def resolved_config():
        return json.dumps(
            {
                "services": {
                    "agent": {
                        "image": "alpine:3.22",
                        "env_file": [{"path": str(inherited_env), "required": True}],
                        "environment": {"MODE": inherited_env.read_text().strip()},
                    }
                }
            }
        )

    async def run_process(target, arguments, *, on_output=None):
        argv = arguments("private")
        calls.append((target, argv, on_output))
        if compose_command(argv) == "config":
            result = config_result or ComposeResult(0, resolved_config())
            return result
        return ComposeResult(1, "missing image")

    service._run_process = run_process
    plan = service.preview(project, "recreate")
    return project, service, plan, calls, inherited_env, base_file


async def test_extends_environment_allows_one_consented_retry_when_unchanged(tmp_path, monkeypatch):
    project, service, plan, calls, _env_file, _base_file = make_extends_target(
        tmp_path, monkeypatch
    )
    fingerprint = await service.capture_retry_environment(plan)
    assert not mutating_calls(calls)
    config_argv = calls[-1][1]
    assert compose_command(config_argv) == "config"
    assert "--format" in config_argv and "json" in config_argv
    assert str(project.files[0]) in config_argv
    assert "--project-directory" in config_argv
    assert "--pull" not in config_argv and "up" not in config_argv
    assert all(call[2] is None for call in calls)

    result = await service.run(
        plan, confirmed=True, pull_missing=True, retry_fingerprint=fingerprint
    )

    assert result.exit_code == 1
    assert len(mutating_calls(calls)) == 1
    retry_argv = mutating_calls(calls)[0][1]
    assert compose_command(retry_argv) == "up"
    assert retry_argv[retry_argv.index("--pull") + 1] == "missing"
    assert retry_argv[retry_argv.index("--project-name") + 1] == "agente"


async def test_changed_inherited_runtime_env_prevents_mutating_retry(tmp_path, monkeypatch):
    _project, service, plan, calls, inherited_env, _base_file = make_extends_target(
        tmp_path, monkeypatch
    )
    fingerprint = await service.capture_retry_environment(plan)
    inherited_env.write_text("MODE=changed\n")

    with pytest.raises(ComposeError, match="environment changed"):
        await service.run(plan, confirmed=True, pull_missing=True, retry_fingerprint=fingerprint)
    assert not mutating_calls(calls)


@pytest.mark.parametrize(
    "probe_result",
    [
        ComposeResult(1, "private-resolved-config"),
        ComposeResult(0, "not-json private-resolved-config"),
        ComposeResult(0, "x" * (compose.MAX_OUTPUT_BYTES + 1)),
    ],
    ids=["config-error", "invalid-json", "truncated-config"],
)
async def test_invalid_or_truncated_config_probe_denies_retry_without_exposing_output(
    tmp_path, monkeypatch, probe_result
):
    _project, service, plan, calls, _env_file, _base_file = make_extends_target(
        tmp_path, monkeypatch, config_result=probe_result
    )

    with pytest.raises(ComposeError, match="resolve the Compose runtime") as error:
        await service.capture_retry_environment(plan)
    assert "private-resolved-config" not in str(error.value)
    assert not mutating_calls(calls)


async def test_retry_preflight_is_checked_before_and_after_config_probe(retry_target):
    project, service, calls = retry_target
    plan = service.preview(project, "recreate")
    fingerprint = await service.capture_retry_environment(plan)
    preflight_checks = iter((True, False))

    with pytest.raises(ComposeError, match="Launch profile changed"):
        await service.run(
            plan,
            confirmed=True,
            pull_missing=True,
            retry_fingerprint=fingerprint,
            retry_preflight=lambda: next(preflight_checks),
        )

    assert not mutating_calls(calls)


async def test_consent_retry_keeps_original_plan_and_default_never(retry_target):
    project, service, calls = retry_target
    plan = service.preview(project, "rebuild")
    fingerprint = await service.capture_retry_environment(plan)
    await service.run(plan, confirmed=True)
    await service.run(plan, confirmed=True, pull_missing=True, retry_fingerprint=fingerprint)
    mutations = mutating_calls(calls)
    first, second = (call[1] for call in mutations)
    pull_index = first.index("--pull")
    assert first[pull_index + 1] == "never"
    assert second[pull_index + 1] == "missing"
    assert (
        first[: pull_index + 1] + first[pull_index + 2 :]
        == second[: pull_index + 1] + second[pull_index + 2 :]
    )
    assert mutations[0][0] == mutations[1][0] == project
