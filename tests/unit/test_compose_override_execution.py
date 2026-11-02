import asyncio
import json
import stat
from pathlib import Path

import pytest

import debugpilot.docker.compose as compose
from debugpilot.docker.compose import (
    ComposeError,
    ComposeProject,
    ComposeResult,
    ComposeService,
)
from debugpilot.storage.config import Settings


class _Output:
    def __init__(self, data=b"started\n"):
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


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def _read_json_bytes(data):
    return json.loads(data)


def _exists(path):
    return path.exists()


def _read_bytes(path):
    return path.read_bytes()


def _command(argv):
    index = argv.index("compose") + 1
    while argv[index] in {"--project-directory", "--project-name", "--env-file", "-f"}:
        index += 2
    return argv[index]


@pytest.fixture
def override_target(tmp_path, monkeypatch):
    source = tmp_path / "compose.yaml"
    original = b"services:\n  api:\n    image: example/api\n"
    source.write_bytes(original)
    canonical = {
        "name": "demo",
        "services": {
            "api": {
                "image": "example/api",
                "environment": {
                    "KEEP": "original",
                    "MODE": "old",
                    "$LITERAL_KEY": "$BASE_VALUE",
                },
                "ports": ["8080:80"],
                "volumes": [f"{tmp_path}/data:/data"],
            }
        },
    }
    monkeypatch.setattr(compose.shutil, "which", lambda _name: "/tools/docker")
    project = ComposeProject.create(
        tmp_path,
        ("compose.yaml",),
        "demo",
        service_overrides={
            "services": {
                "api": {
                    "environment": {"MODE": "literal-$VALUE", "TOKEN": "sensitive-test-value"},
                    "ports": ["9000:80"],
                }
            }
        },
    )
    service = ComposeService(Settings())
    calls = []
    config_files = []
    config_payloads = []
    process_callbacks = []

    async def create(*argv, **kwargs):
        command = _command(argv)
        calls.append((argv, kwargs))
        config_dir = Path(kwargs["env"]["DOCKER_CONFIG"])
        assert _exists(config_dir)
        if command == "config":
            return _Process(json.dumps(canonical).encode())
        compose_files = [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "-f"]
        config_files.append(Path(compose_files[0]))
        assert len(compose_files) == 1
        assert _exists(config_files[-1])
        assert _mode(config_files[-1]) == 0o600
        config_payloads.append(_read_bytes(config_files[-1]))
        return _Process()

    monkeypatch.setattr(compose.asyncio, "create_subprocess_exec", create)
    run_process = service._run_process

    async def tracked_process(*args, on_output=None, effective_json=None):
        process_callbacks.append(on_output)
        return await run_process(*args, on_output=on_output, effective_json=effective_json)

    service._run_process = tracked_process
    return (
        project,
        service,
        calls,
        config_files,
        source,
        original,
        process_callbacks,
        config_payloads,
    )


async def test_overrides_run_from_private_effective_json_and_retry_reuses_snapshot(override_target):
    (
        project,
        service,
        calls,
        config_files,
        source,
        original,
        process_callbacks,
        config_payloads,
    ) = override_target
    plan = service.preview(project, "recreate")
    displayed = repr(project) + plan.display
    assert "sensitive-test-value" not in displayed
    assert str(source) not in plan.display
    assert "effective-compose.json" in plan.display
    callbacks = []
    fingerprint = await service.capture_retry_environment(plan)
    assert len(calls) == 1 and _command(calls[0][0]) == "config"
    assert process_callbacks == [None]

    result = await service.run(
        plan,
        confirmed=True,
        pull_missing=True,
        retry_fingerprint=fingerprint,
        on_output=callbacks.append,
    )

    assert result == ComposeResult(0, "started\n")
    assert len(calls) == 2
    argv, kwargs = calls[-1]
    assert _command(argv) == "up"
    assert argv[argv.index("--pull") + 1] == "missing"
    assert str(source) not in argv
    assert project.workspace == kwargs["cwd"]
    private_file = config_files[-1]
    effective = _read_json_bytes(config_payloads[0])
    assert effective["services"]["api"]["environment"] == {
        "KEEP": "original",
        "MODE": "literal-$$VALUE",
        "$LITERAL_KEY": "$$BASE_VALUE",
        "TOKEN": "sensitive-test-value",
    }
    assert effective["services"]["api"]["ports"] == ["9000:80"]
    assert effective["services"]["api"]["volumes"] == [f"{project.workspace}/data:/data"]
    assert not _exists(private_file)
    assert _read_bytes(source) == original
    assert "sensitive-test-value" not in repr(project) + plan.display + repr(callbacks)
    assert callbacks == ["started"]
    assert len(process_callbacks) == 2 and process_callbacks[1] is not None


async def test_unknown_override_target_fails_before_mutating_spawn(override_target):
    project, service, calls, _files, source, original, _callbacks, _payloads = override_target
    unknown = ComposeProject.create(
        project.workspace,
        project.files,
        project.project_name,
        service_overrides={"services": {"missing": {"ports": []}}},
    )
    plan = service.preview(unknown, "recreate")
    with pytest.raises(ComposeError, match="service overrides") as error:
        await service.run(plan, confirmed=True)
    assert "missing" not in str(error.value)
    assert len(calls) == 1 and _command(calls[0][0]) == "config"
    assert _read_bytes(source) == original


async def test_empty_override_ports_clear_canonical_ports(override_target):
    project, service, _calls, _files, source, original, _callbacks, payloads = override_target
    cleared = ComposeProject.create(
        project.workspace,
        project.files,
        project.project_name,
        service_overrides={"services": {"api": {"ports": []}}},
    )

    await service.run(service.preview(cleared, "recreate"), confirmed=True)

    effective = _read_json_bytes(payloads[0])
    assert effective["services"]["api"]["ports"] == []
    assert _read_bytes(source) == original


async def test_changed_overrides_invalidate_approved_retry_without_mutating_spawn(override_target):
    project, service, calls, _files, source, original, _callbacks, _payloads = override_target
    approved = service.preview(project, "recreate")
    fingerprint = await service.capture_retry_environment(approved)
    changed = ComposeProject.create(
        project.workspace,
        project.files,
        project.project_name,
        service_overrides={"services": {"api": {"environment": {"MODE": "different"}}}},
    )

    with pytest.raises(ComposeError, match="runtime environment changed") as error:
        await service.run(
            service.preview(changed, "recreate"),
            confirmed=True,
            pull_missing=True,
            retry_fingerprint=fingerprint,
        )

    assert "different" not in str(error.value)
    assert len(calls) == 1 and _command(calls[0][0]) == "config"
    assert _read_bytes(source) == original


def test_malformed_public_overrides_fail_without_mutating_source(override_target):
    project, _service, calls, _files, source, original, _callbacks, _payloads = override_target
    with pytest.raises(ComposeError, match="Invalid service overrides") as error:
        ComposeProject.create(
            project.workspace,
            project.files,
            project.project_name,
            service_overrides={"services": {"api": {"environment": {"TOKEN": None}}}},
        )

    assert "None" not in str(error.value)
    assert calls == []
    assert _read_bytes(source) == original


async def test_private_effective_file_is_removed_when_cancelled(override_target, monkeypatch):
    project, service, calls, config_files, source, original, _callbacks, _payloads = override_target
    plan = service.preview(project, "recreate")
    original_create = compose.asyncio.create_subprocess_exec
    started = asyncio.Event()
    read_started = asyncio.Event()
    released = asyncio.Event()
    temp_directories = []
    callbacks = []

    class BlockingOutput:
        async def read(self, _size):
            read_started.set()
            await released.wait()
            return b""

    class CancellableProcess:
        pid = None
        returncode = None

        def __init__(self):
            self.stdout = BlockingOutput()

        def kill(self):
            self.returncode = 0
            released.set()

        async def wait(self):
            return self.returncode

    async def create(*argv, **kwargs):
        if _command(argv) == "config":
            return await original_create(*argv, **kwargs)
        private_files = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "-f"]
        config_files.append(Path(private_files[0]))
        temp_directories.append(Path(private_files[0]).parent)
        assert _exists(config_files[-1])
        started.set()
        return CancellableProcess()

    def forbidden_killpg(*_args):
        raise AssertionError("fake cancellation must not signal an operating-system process")

    monkeypatch.setattr(compose.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(compose.os, "killpg", forbidden_killpg)
    operation = asyncio.create_task(service.run(plan, confirmed=True, on_output=callbacks.append))
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.wait_for(read_started.wait(), timeout=1)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(operation, timeout=1)

    assert calls and _command(calls[0][0]) == "config"
    assert not _exists(config_files[-1])
    assert not _exists(temp_directories[-1])
    assert _read_bytes(source) == original
    assert callbacks == []


async def test_private_effective_file_prepare_failure_is_generic_and_cleans_up(
    override_target, monkeypatch
):
    project, service, calls, _files, source, original, _callbacks, _payloads = override_target
    plan = service.preview(project, "recreate")
    original_open = compose.os.open
    temporary_directories = []

    def fail_effective_file(path, flags, mode=0o777, *, dir_fd=None):
        if Path(path).name == "effective-compose.json":
            temporary_directories.append(Path(path).parent)
            raise OSError("sensitive-test-value private-file failure")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(compose.os, "open", fail_effective_file)
    with pytest.raises(ComposeError, match="private Compose configuration") as error:
        await service.run(plan, confirmed=True)

    assert "sensitive-test-value" not in str(error.value)
    assert error.value.__cause__ is None
    assert len(calls) == 1 and _command(calls[0][0]) == "config"
    assert temporary_directories and not _exists(temporary_directories[-1])
    assert _read_bytes(source) == original


async def test_private_effective_file_is_removed_when_child_spawn_fails(
    override_target, monkeypatch
):
    (
        project,
        service,
        calls,
        config_files,
        _source,
        _original,
        _callbacks,
        _payloads,
    ) = override_target
    plan = service.preview(project, "recreate")
    original_create = compose.asyncio.create_subprocess_exec

    async def fail_mutation(*argv, **kwargs):
        if _command(argv) == "up":
            config = [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "-f"]
            config_files.append(Path(config[0]))
            assert _exists(Path(config[0]))
            raise OSError("spawn failure")
        return await original_create(*argv, **kwargs)

    monkeypatch.setattr(compose.asyncio, "create_subprocess_exec", fail_mutation)
    with pytest.raises(ComposeError, match="Cannot start"):
        await service.run(plan, confirmed=True)
    assert config_files and not _exists(config_files[-1])
    assert len(calls) == 1 and _command(calls[0][0]) == "config"
