import asyncio
import sys
from pathlib import Path

import pytest
from test_compose import Process, fake_process

import debugpilot.docker.compose as compose
from debugpilot.docker.compose import ComposeError, ComposeProject, ComposeService
from debugpilot.storage.config import Settings


@pytest.fixture(name="project")
def launch_project(tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}")
    return ComposeProject.create(tmp_path, (Path("compose.yaml"),), "demo")


@pytest.fixture(name="service")
def launch_service(monkeypatch):
    monkeypatch.setattr(compose.shutil, "which", lambda _name: "/tools/docker")
    return ComposeService(Settings())


def test_start_does_not_force_recreate(project, service):
    plan = service.preview(project, "start")
    args = plan._arguments("private")
    assert "up" in args and "-d" in args and "--force-recreate" not in args
    assert args[args.index("--pull") + 1] == "never"
    assert "--build" not in args


async def test_inspection_resolves_declared_name_without_override(project, service, monkeypatch):
    captured = fake_process(monkeypatch, Process(b'{"name":"dp-demo-orders","services":{}}'))
    result = await service.inspect_project(project.workspace, project.files)
    assert result.project_name == "dp-demo-orders"
    assert result.files == project.files
    assert "--project-name" not in captured["argv"]
    assert captured["argv"][-3:] == ("config", "--format", "json")
    assert "up" not in captured["argv"]
    assert "--pull" not in captured["argv"]


async def test_inspection_validates_files_before_spawn(project, service, monkeypatch):
    captured = fake_process(monkeypatch, Process())
    with pytest.raises(ComposeError):
        await service.inspect_project(project.workspace, (Path("../outside.yaml"),))
    assert captured["calls"] == []


@pytest.mark.parametrize(
    "data,code",
    [(b"secret parse error", 1), (b"bad json", 0), (b"{}", 0), (b"x" * 270000, 0)],
    ids=["exit", "json", "missing-name", "truncated"],
)
async def test_inspection_never_exposes_config_errors(project, service, monkeypatch, data, code):
    fake_process(monkeypatch, Process(data, exit_code=code))
    with pytest.raises(ComposeError, match="Cannot inspect Compose configuration") as error:
        await service.inspect_project(project.workspace, project.files)
    assert "secret" not in str(error.value)


async def test_inspection_uses_isolated_environment_and_cancellation(project, service, monkeypatch):
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "private-sentinel")
    monkeypatch.setenv("DOCKER_CONTEXT", "private-sentinel")
    process = Process(block=True)
    captured = fake_process(monkeypatch, process)
    task = asyncio.create_task(service.inspect_project(project.workspace, project.files))
    await asyncio.wait_for(process.stdout.started.wait(), 2)
    assert "private-sentinel" not in str(captured["env"])
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.waited and process.killed
    assert not captured["private_config"].exists()


async def test_inspection_rejects_file_change_during_config(project, service, monkeypatch):
    process = Process(b'{"name":"demo"}')
    original_wait = process.wait

    async def changed():
        project.files[0].write_text("name: different\nservices: {}")
        return await original_wait()

    process.wait = changed
    fake_process(monkeypatch, process)
    with pytest.raises(ComposeError, match="Cannot inspect"):
        await service.inspect_project(project.workspace, project.files)


async def test_real_isolated_fake_cli_reads_lab_declared_identity(tmp_path, service, monkeypatch):
    lab = (await asyncio.to_thread(Path(__file__).resolve)).parents[
        2
    ] / "examples/multi-project/orders/compose.yaml"
    file = tmp_path / "compose.yaml"
    file.write_bytes(lab.read_bytes())
    cli = tmp_path / "fake_cli.py"
    cli.write_text(
        "import json,pathlib,sys\n"
        "args=sys.argv[1:]\n"
        "assert '--project-name' not in args and args[-3:]==['config','--format','json']\n"
        "config=pathlib.Path(args[args.index('--config')+1])/'config.json'\n"
        "assert set(json.loads(config.read_text())) <= {'cliPluginsExtraDirs'}\n"
        "text=pathlib.Path(args[args.index('-f')+1]).read_text()\n"
        "lines=(line for line in text.splitlines() if line.startswith('name:'))\n"
        "name=next(lines).split(':',1)[1].strip()\n"
        "print(json.dumps({'name':name,'private':'not displayed'}))\n"
    )
    original = compose.ComposePlan._arguments
    monkeypatch.setattr(
        compose.ComposePlan,
        "_arguments",
        lambda plan, config: (sys.executable, str(cli), *original(plan, config)[1:]),
    )
    resolved = await service.inspect_project(tmp_path, (file,))
    assert resolved.project_name == "dp-demo-orders"
    assert not hasattr(resolved, "private")


async def test_start_without_confirmation_never_spawns(project, service, monkeypatch):
    captured = fake_process(monkeypatch, Process())
    with pytest.raises(ComposeError, match="confirmation"):
        await service.run(service.preview(project, "start"))
    assert captured["calls"] == []
