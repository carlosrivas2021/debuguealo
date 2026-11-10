from __future__ import annotations

import asyncio
import codecs
import os
import re
import select
import shutil
import signal
import struct
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from debugpilot.core.models import ContainerInfo
from debugpilot.storage.config import Settings

MAX_ROWS = 200
MAX_COLUMNS = 500
MAX_READ = 64 * 1024
_CONTAINER_ID = re.compile(r"[0-9a-fA-F]{64}\Z")


class TerminalUnavailable(RuntimeError):
    """The requested native terminal backend is unavailable or invalid."""


def _dimensions(rows: int, columns: int) -> tuple[int, int]:
    return max(2, min(MAX_ROWS, rows)), max(2, min(MAX_COLUMNS, columns))


def _windows_platform() -> bool:
    return os.name == "nt"


def _host_argv() -> list[str]:
    name = "bash.exe" if _windows_platform() else "bash"
    bash = shutil.which(name)
    if not bash:
        raise TerminalUnavailable(
            f"{name} was not found on PATH; install Bash to open a host terminal."
        )
    return [bash, "--noprofile", "--norc", "-i"]


def _docker_argv(
    container: ContainerInfo, endpoint: str, cwd: Path
) -> tuple[list[str], dict[str, str]]:
    if container.state.lower() != "running":
        raise TerminalUnavailable(f"Container {container.name} is not running.")
    if not _CONTAINER_ID.fullmatch(container.id):
        raise TerminalUnavailable("Container ID must be a full 64-character Docker ID.")
    try:
        Settings(docker_endpoint=endpoint)
    except (TypeError, ValueError) as exc:
        raise TerminalUnavailable(str(exc)) from None
    docker = shutil.which("docker")
    if not docker:
        raise TerminalUnavailable("Docker CLI was not found on PATH.")
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("DOCKER_")}
    return [docker, "--host", endpoint, "exec", "-it", container.id, "/bin/sh"], env


def _posix_argv(argv: list[str]) -> list[str]:
    # The short-lived bootstrap owns its session and controlling terminal before exec.
    bootstrap = (
        "import fcntl,os,termios; fcntl.ioctl(0,termios.TIOCSCTTY,0); "
        "os.tcsetpgrp(0,os.getpgrp()); os.execvpe(sys.argv[1],sys.argv[1:],os.environ)"
    )
    return [sys.executable, "-c", "import sys; " + bootstrap, *argv]


GROUP_GRACE_SECONDS = 2.0
GROUP_KILL_WAIT_SECONDS = 1.0


async def _wait_for_group_exit(pgid: int, deadline: float) -> bool:
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(0.01, remaining))


@dataclass
class TerminalSession:
    """A bounded native pseudo-terminal session; no process starts until open()."""

    on_output: Callable[[str], None]
    on_exit: Callable[[], None] | None = None
    process: object | None = None
    _fd: int | None = None
    _reader: asyncio.Task[None] | None = None
    _closed: bool = True
    _windows: bool = False
    _decoder: object = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")("replace")
    )
    _exit_notified: bool = True
    _docker_config: tempfile.TemporaryDirectory | None = field(default=None, init=False, repr=False)

    async def open_host(self, cwd: Path, rows: int = 24, columns: int = 80) -> None:
        await self._open(_host_argv(), cwd, _dimensions(rows, columns))

    async def open_container(
        self, container: ContainerInfo, endpoint: str, cwd: Path,
        rows: int = 24, columns: int = 80,
    ) -> None:
        argv, env = _docker_argv(container, endpoint, cwd)
        await self._open(argv, cwd, _dimensions(rows, columns), env)

    async def _open(
        self, argv: list[str], cwd: Path, dimensions: tuple[int, int],
        env: dict[str, str] | None = None, *, docker_config: bool | None = None,
    ) -> None:
        if not await asyncio.to_thread(cwd.is_dir):
            raise TerminalUnavailable(f"Terminal working directory does not exist: {cwd}")
        if not self._closed:
            await self.close_session()
        # A private Docker config isolates container shells; by default it follows `env`,
        # as before. Code runs pass their environment without it.
        isolate = env is not None if docker_config is None else docker_config
        docker_config = None
        try:
            if isolate:
                docker_config = tempfile.TemporaryDirectory(prefix="debugpilot-exec-")
                env = {**env, "DOCKER_CONFIG": docker_config.name}
            if _windows_platform():
                self._open_windows(argv, cwd, dimensions, env)
            else:
                self._open_posix(argv, cwd, dimensions, env)
        except BaseException as exc:
            if docker_config is not None:
                docker_config.cleanup()
            if isinstance(exc, (OSError, ValueError)):
                raise TerminalUnavailable(f"Unable to open terminal: {exc}") from exc
            raise
        self._docker_config = docker_config
        self._closed = False
        self._exit_notified = False
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._reader = asyncio.create_task(self._read_loop())

    def _open_posix(
        self, argv: list[str], cwd: Path, dimensions: tuple[int, int], env: dict[str, str] | None
    ) -> None:
        import fcntl
        import pty
        import subprocess
        import termios

        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", *dimensions, 0, 0))
            self.process = subprocess.Popen(
                _posix_argv(argv), cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave,
                close_fds=True, start_new_session=True,
            )
        except BaseException:
            os.close(master)
            os.close(slave)
            raise
        os.close(slave)
        os.set_blocking(master, False)
        self._fd = master

    def _open_windows(
        self, argv: list[str], cwd: Path, dimensions: tuple[int, int], env: dict[str, str] | None
    ) -> None:
        try:
            from winpty import PtyProcess
        except ImportError as exc:
            raise TerminalUnavailable(
                "Windows ConPTY support requires the optional pywinpty package."
            ) from exc
        self.process = PtyProcess.spawn(argv, cwd=str(cwd), dimensions=dimensions, env=env)
        self._windows = True

    async def _read_loop(self) -> None:
        docker_config = self._docker_config
        try:
            while not self._closed:
                try:
                    if self._windows:
                        chunk = await asyncio.to_thread(self.process.read, 4096)
                        text = chunk
                    else:
                        await asyncio.sleep(0.015)
                        # Closing may release the PTY while this reader is asleep.
                        if self._closed or self._fd is None:
                            break
                        try:
                            data = os.read(self._fd, MAX_READ)
                        except BlockingIOError:
                            continue
                        text = self._decoder.decode(data, final=not data)
                        if data and not text:
                            # A partial UTF-8 character is not byte-stream EOF.
                            continue
                    if not text:
                        break
                    self.on_output(text[:MAX_READ])
                except (EOFError, OSError, ValueError):
                    break
        finally:
            self._closed = True
            process, self.process = self.process, None
            if process is not None and not self._windows:
                try:
                    await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=0.5)
                except TimeoutError:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=1.0)
                    except TimeoutError:
                        pass
            fd, self._fd = self._fd, None
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            self._release_docker_config(docker_config)
            if not self._exit_notified:
                self._exit_notified = True
                if self.on_exit is not None:
                    self.on_exit()

    def _release_docker_config(self, config: tempfile.TemporaryDirectory | None) -> None:
        if config is not None and self._docker_config is config:
            self._docker_config = None
            config.cleanup()

    def write(self, text: str) -> None:
        if self._closed or not self.process:
            return
        data = text.encode("utf-8", errors="replace")[:MAX_READ]
        if self._windows:
            self.process.write(data.decode("utf-8", errors="replace"))
        elif self._fd is not None:
            deadline = time.monotonic() + 0.25
            view = memoryview(data)
            while view and time.monotonic() < deadline:
                try:
                    written = os.write(self._fd, view)
                    view = view[written:]
                except BlockingIOError:
                    select.select([], [self._fd], [], max(0, deadline - time.monotonic()))
                except OSError:
                    return

    def resize(self, rows: int, columns: int) -> None:
        rows, columns = _dimensions(rows, columns)
        if self._closed or not self.process:
            return
        if self._windows:
            self.process.setwinsize(rows, columns)
        else:
            import fcntl
            import termios

            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))

    async def close_session(self) -> None:
        if self._closed and self.process is None:
            if self._reader is not None and self._reader.done():
                self._reader = None
            if self._reader is None:
                self._release_docker_config(self._docker_config)
            return
        docker_config = self._docker_config
        self._closed = True
        process, self.process = self.process, None
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            if process is not None:
                if self._windows:
                    try:
                        process.close(force=True)
                    except OSError:
                        pass
                else:
                    started = time.monotonic()
                    terminated = False
                    try:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGTERM)
                            terminated = True
                        await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=0.5)
                    except TimeoutError:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        try:
                            await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=1.0)
                        except TimeoutError:
                            pass
                    except (OSError, ProcessLookupError):
                        pass

                    # Reaping the helper alone is insufficient: closing the PTY can end it
                    # at once while owned descendants in its process group are still
                    # shutting down. Give them their grace period, then force the group.
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        pass
                    else:
                        if not terminated:
                            try:
                                os.killpg(process.pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                        graceful = started + GROUP_GRACE_SECONDS
                        if not await _wait_for_group_exit(process.pid, graceful):
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            forced = graceful + GROUP_KILL_WAIT_SECONDS
                            if not await _wait_for_group_exit(process.pid, forced):
                                raise TimeoutError(
                                    "Timed out waiting for the owned process group to exit."
                                )
        except BaseException:
            # Preserve an owner handle for a later close retry.
            if process is not None and self.process is None:
                self.process = process
            raise
        finally:
            reader, self._reader = self._reader, None
            if reader and reader is not asyncio.current_task():
                reader.cancel()
                try:
                    await asyncio.wait_for(reader, timeout=1.0)
                except (asyncio.CancelledError, TimeoutError):
                    pass
            self._windows = False
            self._release_docker_config(docker_config)
            if not self._exit_notified:
                self._exit_notified = True
                if self.on_exit is not None:
                    self.on_exit()
