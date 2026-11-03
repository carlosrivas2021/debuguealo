"""Managed local commands, independent of Docker and host shell policy."""

import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

from debugpilot.terminal.session import TerminalSession, TerminalUnavailable


def command_argv(command: tuple[str, ...]) -> list[str]:
    executable = shutil.which(command[0])
    if not executable:
        raise TerminalUnavailable(f"Executable not found: {command[0]}")
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        # npm's Windows shim is a batch file. Run its JS entry directly to avoid
        # cmd.exe interpreting metacharacters in user-supplied argv arguments.
        entry = Path(executable).parent / "node_modules/npm/bin/npm-cli.js"
        node = shutil.which("node")
        if Path(executable).stem.lower() != "npm" or not entry.is_file() or not node:
            raise TerminalUnavailable(
                "Batch launchers are unsupported; use the underlying executable or script."
            )
        return [node, str(entry), *command[1:]]
    return [executable, *command[1:]]


class CodeSession(TerminalSession):
    def __init__(self, on_output, on_exit=None):
        super().__init__(on_output=on_output, on_exit=self._finished)
        self._notify_exit = on_exit
        self._status_dir = None
        self.exit_code: int | None = None
        self.error: str | None = None
        self._stopping = False

    async def open_command(self, command, cwd, rows=24, columns=80):
        await self.close_session()
        argv = command_argv(tuple(command))
        self.exit_code = None
        self.error = None
        self._stopping = False
        self._status_dir = tempfile.TemporaryDirectory(prefix="debugpilot-code-")
        helper = Path(__file__).with_name("_code_worker.py")
        status = Path(self._status_dir.name) / "status.json"
        try:
            await self._open(
                [sys.executable, str(helper), str(status), *argv], cwd, (rows, columns)
            )
        except BaseException:
            self._cleanup_status()
            raise

    def _open_windows(self, argv, cwd, dimensions, env):
        super()._open_windows(argv, cwd, dimensions, env)
        # PtyProcess's socket bridge can retain an open socket after target exit.
        self.process.fileobj.settimeout(0.1)

    async def _read_loop(self):
        if not self._windows:
            await super()._read_loop()
            return
        process = self.process
        ended_at = None
        loop = asyncio.get_running_loop()
        try:
            while not self._closed:
                try:
                    data = await asyncio.to_thread(process.fileobj.recv, 65536)
                except TimeoutError:
                    if not process.isalive():
                        ended_at = ended_at or loop.time()
                        # Drain the asynchronous ConPTY socket bridge after exit.
                        if loop.time() - ended_at >= 0.5:
                            break
                    continue
                if not data:
                    break
                if data != b"0011Ignore":
                    self.on_output(self._decoder.decode(data))
        except (EOFError, OSError):
            pass
        finally:
            self._closed = True
            self._disconnect_windows(process)
            self.process = None
            if not self._exit_notified:
                self._exit_notified = True
                self.on_exit()

    @staticmethod
    def _disconnect_windows(process):
        if process.closed and process.fileobj.fileno() == -1:
            return
        if process.isalive():
            import signal

            try:
                os.kill(process.pid, signal.SIGTERM)
            except OSError:
                if process.isalive():
                    raise
        # Wake both the socket bridge and pending recv before releasing handles.
        try:
            process.fileobj.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        process.fileobj.close()
        process._server.close()
        process.closed = True

    def _finished(self):
        if self._status_dir is not None and not self._stopping:
            status = Path(self._status_dir.name) / "status.json"
            try:
                result = json.loads(status.read_text(encoding="utf-8"))
                self.exit_code = result.get("exit_code")
                self.error = result.get("error")
            except (OSError, ValueError):
                self.error = "Code process ended without an exit status."
        self._cleanup_status()
        if self._notify_exit:
            self._notify_exit()

    def _cleanup_status(self):
        if self._status_dir is not None:
            self._status_dir.cleanup()
            self._status_dir = None

    async def close_session(self):
        self._stopping = True
        # Wake a pending Windows read before TerminalSession cancels the reader.
        if self._windows and self.process is not None:
            self._disconnect_windows(self.process)
        await super().close_session()
        self._cleanup_status()
