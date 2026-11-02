import asyncio
import json
import os
import signal
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

import debugpilot.docker.compose as compose
from debugpilot.docker.compose import (
    ComposeError,
    ComposePlan,
    ComposeProject,
    ComposeService,
)
from debugpilot.storage.config import Settings


@pytest.fixture
def project(tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    (tmp_path / "local.yaml").write_text("services: {}\n")
    return ComposeProject.create(tmp_path, (Path("compose.yaml"), Path("local.yaml")), "demo")


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(compose.shutil, "which", lambda _name: "/tools/docker")
    return ComposeService(Settings())


class Output:
    def __init__(self, data=b"done\n", block=False):
        self.data = data
        self.block = block
        self.started = asyncio.Event()

    async def read(self, size):
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        data, self.data = self.data[:size], self.data[size:]
        return data


class Process:
    def __init__(self, data=b"done\n", exit_code=0, block=False):
        self.stdout = Output(data, block)
        self.returncode = None if block else exit_code
        self.killed = False
        self.waited = False

    def kill(self):
        self.killed = True
        self.returncode = -1
        self.stdout.block = False

    async def wait(self):
        self.waited = True
        return self.returncode


def compose_command(arguments):
    index = arguments.index("compose") + 1
    while arguments[index] in {"--project-directory", "--project-name", "--env-file", "-f"}:
        index += 2
    return arguments[index]


def fake_process(monkeypatch, process, *, config_output=None):
    captured = {"calls": []}

    async def create(*argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        captured["calls"].append(argv)
        config = Path(kwargs["env"]["DOCKER_CONFIG"])
        assert json.loads((config / "config.json").read_text()) in (
            {},
            {"cliPluginsExtraDirs": [str(Path.home() / ".docker" / "cli-plugins")]},
        )
        captured["private_config"] = config
        command = compose_command(argv)
        if command == "config" and config_output is not None:
            return Process(config_output)
        return process

    monkeypatch.setattr(compose.asyncio, "create_subprocess_exec", create)
    return captured


@pytest.mark.parametrize("action", ["restart", "recreate", "rebuild"])
@pytest.mark.parametrize("target", [None, "payments-api"])
async def test_ordered_files_actions_scope_and_explicit_local_target(
    project, service, monkeypatch, action, target
):
    captured = fake_process(monkeypatch, Process())
    plan = service.preview(project, action, target)
    result = await service.run(plan, confirmed=True)
    argv = captured["argv"]
    assert argv[0] == sys.executable and argv[1].endswith("_compose_worker.py")
    assert argv[2] == "/tools/docker" and argv[3] == "--host"
    assert argv[4] == (service.settings.docker_endpoint or compose.default_endpoint())
    assert argv.index(str(project.files[0])) < argv.index(str(project.files[1]))
    assert argv[argv.index("--project-name") + 1] == "demo"
    if action == "restart":
        assert "restart" in argv and "up" not in argv and "--build" not in argv
    else:
        assert "up" in argv and "--force-recreate" in argv and "-d" in argv
        assert argv[argv.index("--pull") + 1] == "never"
        assert ("--build" in argv) == (action == "rebuild")
    assert ("--no-deps" in argv) == bool(target)
    if target:
        assert argv[-1] == target
    assert not captured["private_config"].exists()
    assert result.exit_code == 0 and result.output == "done\n"
    assert str(project.files[0]) in plan.display and action in (plan.action,)


async def test_missing_image_retry_is_explicit_and_preserves_up_arguments(
    project, service, monkeypatch
):
    captured = fake_process(monkeypatch, Process(exit_code=1), config_output=b'{"services":{}}')
    plan = service.preview(project, "recreate")
    fingerprint = await service.capture_retry_environment(plan)
    with pytest.raises(ComposeError, match="boolean"):
        await service.run(plan, confirmed=True, pull_missing="yes")
    await service.run(plan, confirmed=True)
    assert captured["argv"][captured["argv"].index("--pull") + 1] == "never"
    await service.run(plan, confirmed=True, pull_missing=True, retry_fingerprint=fingerprint)
    argv = captured["argv"]
    assert argv[argv.index("--pull") + 1] == "missing"
    assert argv[argv.index("up") + 1] == "-d"
    assert "--force-recreate" in argv
    assert argv[argv.index("--pull") + 1] == "missing"


async def test_missing_image_retry_revalidates_before_spawn(project, service, monkeypatch):
    captured = fake_process(monkeypatch, Process(), config_output=b'{"services":{}}')
    plan = service.preview(project, "rebuild")
    fingerprint = await service.capture_retry_environment(plan)
    project.files[0].write_text("services: {changed: {}}\n")
    with pytest.raises(ComposeError, match="changed"):
        await service.run(plan, confirmed=True, pull_missing=True, retry_fingerprint=fingerprint)
    assert not any(compose_command(arguments) == "up" for arguments in captured["calls"])


async def test_missing_image_retry_revalidates_environment_files_and_action(
    project, service, monkeypatch
):
    environment = project.workspace / "settings.env"
    environment.write_text("MODE=local\n")
    configured = ComposeProject.create(
        project.workspace, project.files, project.project_name, environment_files=(environment,)
    )
    captured = fake_process(monkeypatch, Process(), config_output=b'{"services":{}}')
    plan = service.preview(configured, "recreate")
    fingerprint = await service.capture_retry_environment(plan)
    environment.write_text("MODE=changed\n")
    with pytest.raises(ComposeError, match="changed"):
        await service.run(plan, confirmed=True, pull_missing=True, retry_fingerprint=fingerprint)
    assert not any(compose_command(arguments) == "up" for arguments in captured["calls"])

    restart = service.preview(project, "restart")
    with pytest.raises(ComposeError, match="up actions"):
        await service.run(restart, confirmed=True, pull_missing=True)
    assert not any(compose_command(arguments) == "up" for arguments in captured["calls"])


async def test_output_callback_streams_unicode_complete_lines_before_exit(
    project, service, monkeypatch
):
    script = (
        "import os,time; os.write(1,b'progress\\n'); time.sleep(.3); "
        "os.write(1,b'caf\\xc3'); time.sleep(.1); os.write(1,b'\\xa9\\n')"
    )
    monkeypatch.setattr(
        ComposePlan, "_arguments", lambda _plan, _config: (sys.executable, "-c", script)
    )
    output = []
    progress_seen = asyncio.Event()

    def receive(line):
        output.append(line)
        if line == "progress":
            progress_seen.set()

    operation = asyncio.create_task(
        service.run(service.preview(project, "recreate"), confirmed=True, on_output=receive)
    )
    await asyncio.wait_for(progress_seen.wait(), 2)
    assert not operation.done()
    result = await operation
    assert output == ["progress", "café"]
    assert result.output == "progress\ncafé\n"


async def test_confirmation_and_revalidation_spawn_nothing(project, service, monkeypatch):
    captured = fake_process(monkeypatch, Process())
    plan = service.preview(project, "rebuild")
    with pytest.raises(ComposeError, match="confirm"):
        await service.run(plan)
    with pytest.raises(ComposeError):
        await service.run(replace(plan, service="--all"), confirmed=True)
    project.files[0].write_text("services: {changed: {}}\n")
    with pytest.raises(ComposeError, match="changed"):
        await service.run(plan, confirmed=True)
    assert not captured["calls"]


def test_project_directory_and_up_options_are_strict_and_workspace_bound(project, tmp_path):
    from debugpilot.docker.compose import ComposeUpOptions

    nested = project.workspace / "nested"
    nested.mkdir()
    selected = ComposeProject.create(
        project.workspace,
        project.files,
        project.project_name,
        project_directory=Path("nested"),
        up=ComposeUpOptions(build=True, detach=False, force_recreate=True),
    )
    assert selected.project_directory == nested.resolve()
    assert selected.up == ComposeUpOptions(build=True, detach=False, force_recreate=True)
    for field in ("build", "detach", "force_recreate"):
        with pytest.raises((TypeError, ValueError)):
            ComposeUpOptions(**{field: "--build"})
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    with pytest.raises(ComposeError):
        ComposeProject.create(
            project.workspace, project.files, project.project_name, project_directory=outside
        )
    with pytest.raises(ComposeError):
        ComposeProject.create(
            project.workspace,
            project.files,
            project.project_name,
            project_directory=Path("missing"),
        )


async def test_explicit_project_directory_and_up_flags_preserve_order(
    project, service, monkeypatch
):
    from debugpilot.docker.compose import ComposeUpOptions

    root = project.workspace
    (root / "local" / "agents").mkdir(parents=True)
    (root / "local" / "agents" / "docker-compose.yaml").write_text("services: {}\n")
    (root / "scratchpad").mkdir()
    (root / "scratchpad" / "agents.ports.yaml").write_text("services: {}\n")
    (root / "nested-project").mkdir()
    selected = ComposeProject.create(
        root,
        (Path("local/agents/docker-compose.yaml"), Path("scratchpad/agents.ports.yaml")),
        "nested",
        project_directory=Path("nested-project"),
        up=ComposeUpOptions(build=True, detach=False, force_recreate=True),
    )
    captured = fake_process(monkeypatch, Process())
    await service.run(service.preview(selected, "start"), confirmed=True)
    argv = captured["argv"]
    assert argv[argv.index("--project-directory") + 1] == str(root / "nested-project")
    assert argv.index(str(selected.files[0])) < argv.index(str(selected.files[1]))
    assert "up" in argv and "--build" in argv and "--force-recreate" in argv
    assert "-d" not in argv and "--pull" in argv and argv[argv.index("--pull") + 1] == "never"


async def test_legacy_start_argv_and_restart_rebuild_ignore_profile_up(
    project, service, monkeypatch
):
    from debugpilot.docker.compose import ComposeUpOptions

    legacy = fake_process(monkeypatch, Process())
    await service.run(service.preview(project, "start"), confirmed=True)
    legacy_argv = legacy["argv"]
    assert legacy_argv[legacy_argv.index("--project-directory") + 1] == str(project.workspace)
    assert legacy_argv[legacy_argv.index("up") + 1] == "-d"
    assert "--build" not in legacy_argv and "--force-recreate" not in legacy_argv

    configured = ComposeProject.create(
        project.workspace,
        project.files,
        project.project_name,
        up=ComposeUpOptions(build=True, detach=False, force_recreate=False),
    )
    captured = fake_process(monkeypatch, Process())
    await service.run(service.preview(configured, "rebuild"), confirmed=True)
    argv = captured["argv"]
    assert "-d" in argv and "--build" in argv and "--force-recreate" in argv


async def test_profile_fields_are_revalidated_before_run(project, service, monkeypatch):
    from debugpilot.docker.compose import ComposeUpOptions

    directory = project.workspace / "project"
    directory.mkdir()
    configured = ComposeProject.create(
        project.workspace,
        project.files,
        project.project_name,
        project_directory=directory,
        up=ComposeUpOptions(build=True),
    )
    captured = fake_process(monkeypatch, Process())
    plan = service.preview(configured, "start")
    directory.rename(project.workspace / "moved")
    with pytest.raises(ComposeError):
        await service.run(plan, confirmed=True)
    assert not captured["calls"]


async def test_inspection_preserves_profile_identity_and_options(project, service, monkeypatch):
    from debugpilot.docker.compose import ComposeUpOptions

    directory = project.workspace / "compose-project"
    directory.mkdir()
    captured = fake_process(monkeypatch, Process(b'{"name":"inspected"}'))
    inspected = await service.inspect_project(
        project.workspace,
        project.files,
        project_directory=directory,
        up=ComposeUpOptions(build=True, detach=False),
    )
    assert inspected.project_name == "inspected"
    assert inspected.project_directory == directory.resolve()
    assert inspected.up == ComposeUpOptions(build=True, detach=False)
    assert captured["argv"][captured["argv"].index("--project-directory") + 1] == str(directory)


def test_invalid_project_files_and_service_are_rejected(project, service, tmp_path):
    with pytest.raises(ComposeError):
        ComposeProject.create(tmp_path, (), "demo")
    with pytest.raises(ComposeError):
        ComposeProject.create(tmp_path, (Path("../outside.yaml"),), "demo")
    for name in ("--x", "demo;touch", "UPPER", ""):
        with pytest.raises(ComposeError):
            ComposeProject.create(tmp_path, project.files, name)
    for target in ("--all", "a;b", "../service", ""):
        with pytest.raises(ComposeError):
            service.preview(project, "rebuild", target)
    with pytest.raises(ComposeError):
        service.preview(project, "down")


async def test_ambient_credentials_and_remote_context_are_not_inherited(
    project, service, monkeypatch
):
    for key in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "COMPOSE_FILE",
        "COMPOSE_PROJECT_NAME",
        "AWS_SECRET_ACCESS_KEY",
        "PRIVATE_TOKEN",
    ):
        monkeypatch.setenv(key, "private-sentinel")
    captured = fake_process(monkeypatch, Process())
    await service.run(service.preview(project, "restart"), confirmed=True)
    assert "private-sentinel" not in str(captured["env"])
    assert "DOCKER_CONTEXT" not in captured["env"]
    assert captured["cwd"] == project.workspace
    assert captured["stderr"] == asyncio.subprocess.STDOUT


async def test_windows_system_plugin_locations_survive_environment_isolation(
    project, service, monkeypatch
):
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("ProgramData", r"C:\ProgramData")
    captured = fake_process(monkeypatch, Process())
    await service.run(service.preview(project, "restart"), confirmed=True)
    environment = {key.upper(): value for key, value in captured["env"].items()}
    assert environment["PROGRAMFILES"] == r"C:\Program Files"
    assert environment["PROGRAMDATA"] == r"C:\ProgramData"


async def test_output_is_bounded_and_nonzero_exit_preserved(project, service, monkeypatch):
    process = Process(b"x" * (compose.MAX_OUTPUT_BYTES + 100), exit_code=7)
    fake_process(monkeypatch, process)
    result = await service.run(service.preview(project, "recreate"), confirmed=True)
    assert result.exit_code == 7 and "truncated" in result.output
    assert len(result.output.encode()) <= compose.MAX_OUTPUT_BYTES + 100
    assert process.waited and not process.killed


async def test_cancel_kills_and_reaps_child_and_removes_private_config(
    project, service, monkeypatch
):
    process = Process(block=True)
    captured = fake_process(monkeypatch, process)
    task = asyncio.create_task(service.run(service.preview(project, "rebuild"), confirmed=True))
    await asyncio.wait_for(process.stdout.started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed and process.waited
    assert not captured["private_config"].exists()


async def test_timeout_cleans_up_and_missing_executable_is_understandable(
    project, service, monkeypatch
):
    service.timeout_seconds = 0.01
    process = Process(block=True)
    captured = fake_process(monkeypatch, process)
    with pytest.raises(ComposeError, match="timed out"):
        await service.run(service.preview(project, "restart"), confirmed=True)
    assert process.killed and process.waited
    assert not captured["private_config"].exists()
    monkeypatch.setattr(compose.shutil, "which", lambda _name: None)
    with pytest.raises(ComposeError, match="Docker CLI"):
        ComposeService(Settings()).preview(project, "restart")


async def test_repeated_cancellation_cannot_interrupt_child_reaping(project, service, monkeypatch):
    reaping = asyncio.Event()
    release = asyncio.Event()

    class SlowReap(Process):
        async def wait(self):
            reaping.set()
            await release.wait()
            return await super().wait()

    process = SlowReap(block=True)
    captured = fake_process(monkeypatch, process)
    task = asyncio.create_task(service.run(service.preview(project, "restart"), confirmed=True))
    await asyncio.wait_for(process.stdout.started.wait(), 2)
    task.cancel()
    await asyncio.wait_for(reaping.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and process.killed
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.waited and not captured["private_config"].exists()


async def test_cancellation_during_launch_drains_a_real_childs_full_stdout(
    project, service, monkeypatch
):
    # Harmless Python child in its own session, never Docker. Keep its PID so
    # failure cleanup can signal only the process group this test created.
    create = asyncio.create_subprocess_exec
    ready, release = asyncio.Event(), asyncio.Event()
    child = None

    async def delayed_create(*_args, **_kwargs):
        nonlocal child
        child = await create(
            sys.executable,
            "-c",
            "import sys,time; sys.stdout.buffer.write(b'x'*1048576); "
            "sys.stdout.flush(); time.sleep(30)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        assert os.getpgid(child.pid) == child.pid
        ready.set()
        await release.wait()
        return child

    monkeypatch.setattr(compose.asyncio, "create_subprocess_exec", delayed_create)
    task = asyncio.create_task(service.run(service.preview(project, "restart"), confirmed=True))
    try:
        await asyncio.wait_for(ready.wait(), 2)
        await asyncio.sleep(0.2)  # Let the child fill its private pipe without reading it here.
        task.cancel()
        release.set()
        done, _ = await asyncio.wait({task}, timeout=1)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert done, "Cancellation cleanup hung until the full stdout pipe was drained"
        assert child.returncode is not None
    finally:
        release.set()
        if child is not None and child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await asyncio.wait_for(child.wait(), 1)
        if not task.done():
            task.cancel()
            with pytest.raises((asyncio.CancelledError, TimeoutError)):
                await asyncio.wait_for(task, 1)


async def test_timeout_terminates_plugin_descendants_inheriting_stdout(
    project, service, monkeypatch
):
    started = project.workspace / "started"
    survivor = project.workspace / "survivor"
    descendant = (
        "import time,pathlib; time.sleep(1); "
        f"pathlib.Path({str(survivor)!r}).write_text('still running'); time.sleep(30)"
    )
    launcher = (
        "import subprocess,sys,time,pathlib; "
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
        f"pathlib.Path({str(started)!r}).write_text('launched'); time.sleep(30)"
    )
    # Keep the actual production helper and its process-tree containment, replacing
    # only the trusted executable command. No Docker is invoked.
    monkeypatch.setattr(
        compose.ComposePlan, "_arguments", lambda _self, _config: (sys.executable, "-c", launcher)
    )
    service.timeout_seconds = 0.5
    start = time.monotonic()
    with pytest.raises(ComposeError, match="timed out"):
        await service.run(service.preview(project, "restart"), confirmed=True)
    elapsed = time.monotonic() - start
    assert started.exists(), "Probe did not reach descendant creation"
    assert elapsed < 1.2, "Inherited stdout delayed timeout delivery"
    await asyncio.sleep(1.1)
    assert not survivor.exists(), "A plugin descendant survived cleanup"


async def test_isolation_helper_preserves_real_exit_status(project, service, monkeypatch):
    monkeypatch.setattr(
        compose.ComposePlan,
        "_arguments",
        lambda _self, _config: (sys.executable, "-c", "print('real');exit(7)"),
    )
    result = await service.run(service.preview(project, "restart"), confirmed=True)
    assert result.exit_code == 7 and result.output.strip() == "real"


async def test_profile_process_cwd_and_environment_files_are_bound(project, service, monkeypatch):
    process_cwd = project.workspace / "local"
    process_cwd.mkdir()
    environment = project.workspace / "settings.env"
    environment.write_text("MODE=local\n")
    configured = ComposeProject.create(
        project.workspace,
        project.files,
        project.project_name,
        project_directory=process_cwd,
        process_cwd=process_cwd,
        environment_files=(environment,),
    )
    captured = fake_process(monkeypatch, Process())
    plan = service.preview(configured, "start")
    await service.run(plan, confirmed=True)
    assert captured["cwd"] == process_cwd
    argv = plan._arguments("private")
    assert argv[argv.index("--env-file") + 1] == str(environment)
    environment.write_text("MODE=changed\n")
    with pytest.raises(ComposeError, match="changed"):
        service.preview(configured, "start")


def test_private_config_exposes_only_user_plugin_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(compose.Path, "home", lambda: tmp_path)
    assert compose._private_docker_config() == "{}"
    plugins = tmp_path / ".docker" / "cli-plugins"
    plugins.mkdir(parents=True)
    (tmp_path / ".docker" / "config.json").write_text('{"auths":{"x":"secret"}}')
    assert json.loads(compose._private_docker_config()) == {
        "cliPluginsExtraDirs": [str(plugins)]
    }
