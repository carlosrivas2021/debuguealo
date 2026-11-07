"""Dedicated central code profiles; loading never writes or executes commands."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.config import config_path


@dataclass(frozen=True)
class RemoteAttach:
    host: str
    port: int
    remote_root: str


GoAttach = RemoteAttach


def parse_remote_attach(value: object) -> RemoteAttach:
    """Validate the intentionally loopback-only attach schema."""
    if (not isinstance(value, dict) or set(value) != {'host', 'port', 'remoteRoot'}
            or value.get('host') != '127.0.0.1'
            or type(value.get('port')) is not int or not 1 <= value['port'] <= 65535
            or not CodeProjectStore._text(value.get('remoteRoot'))):
        raise ValueError
    raw_root = value['remoteRoot']
    remote_root = PurePosixPath(raw_root)
    if ('\\' in raw_root or not remote_root.is_absolute() or '..' in remote_root.parts
            or str(remote_root) != raw_root):
        raise ValueError
    return RemoteAttach('127.0.0.1', value['port'], str(remote_root))


@dataclass(frozen=True)
class CodeProject:
    name: str
    root: Path
    command: tuple[str, ...]
    node_debug: tuple[str, ...] | None = None
    go_attach: RemoteAttach | None = None
    python_attach: RemoteAttach | None = None

    @property
    def attach(self) -> RemoteAttach | None:
        return self.go_attach or self.python_attach


def is_node_command(command):
    return bool(command) and Path(command[0]).name.lower() in {'node', 'node.exe'}


def is_npm_command(command):
    return bool(command) and Path(command[0]).name.lower() in {'npm', 'npm.cmd', 'npm.exe'}


def valid_node_target(command):
    return (isinstance(command, (list, tuple)) and 2 <= len(command) <= 128
            and all(CodeProjectStore._text(arg) for arg in command)
            and is_node_command(command) and not command[1].startswith('-')
            and Path(command[1]).suffix.lower() in {'.js', '.cjs', '.mjs'})


class CodeProjectStore:
    def __init__(self):
        self.path = config_path().parent / "projects" / "launch.json"

    def ensure_launch_file(self) -> Path:
        """Publish an empty starter only on explicit request; never replace a file."""
        if self.path.exists():
            return self.path
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(b'{"version": 1, "configurations": []}\n')
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                pass  # A concurrent editor owns the file; keep it untouched.
            return self.path
        except OSError:
            raise ConfigurationError("Cannot create code launch.json; check permissions.") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def profiles(self) -> list[CodeProject]:
        try:
            with self.path.open("rb") as stream:
                data = stream.read(256 * 1024 + 1)
        except FileNotFoundError:
            return []
        except OSError:
            raise ConfigurationError("Cannot read code launch.json; check permissions.") from None
        try:
            if len(data) > 256 * 1024:
                raise ValueError
            document = json.loads(data)
            if not isinstance(document, dict) or type(document.get("version")) is not int:
                raise ValueError
            entries = document.get("configurations")
            if document["version"] != 1 or not isinstance(entries, list) or len(entries) > 128:
                raise ValueError
            profiles = []
            names = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError
                name = entry.get("name")
                folder = entry.get("workspaceFolder")
                command = entry.get("command")
                if not self._text(name) or name in names or not self._text(folder):
                    raise ValueError
                root = Path(folder)
                if not root.is_absolute() or not root.is_dir():
                    raise ValueError
                if 'goAttach' in entry and 'pythonAttach' in entry:
                    raise ConfigurationError(
                        'Invalid attach profile: use either goAttach or pythonAttach, not both.'
                    )
                go_attach = python_attach = None
                for field in ('goAttach', 'pythonAttach'):
                    if field not in entry:
                        continue
                    try:
                        parsed = parse_remote_attach(entry[field])
                    except ValueError:
                        raise ConfigurationError(
                            f'Invalid {field}: use host 127.0.0.1, integer port 1..65535, '
                            'and an absolute POSIX remoteRoot without parent segments.'
                        ) from None
                    if field == 'goAttach':
                        go_attach = parsed
                    else:
                        python_attach = parsed
                attach = go_attach or python_attach
                if command is None and attach is None:
                    raise ValueError
                if command is None:
                    command = []
                if not isinstance(command, list) or len(command) > 128:
                    raise ValueError
                if (not command and attach is None) or any(
                        not self._text(arg) for arg in command):
                    raise ValueError
                node_debug = None
                if 'nodeDebug' in entry:
                    target = entry['nodeDebug']
                    if not is_npm_command(command) or not valid_node_target(target):
                        raise ConfigurationError(
                            "Invalid nodeDebug: use a Node script argv array only for npm "
                            "profiles: [node, server.js, args...], without runtime flags."
                        )
                    node_debug = tuple(target)
                profiles.append(CodeProject(name, root.resolve(strict=True), tuple(command),
                                            node_debug, go_attach, python_attach))
                names.add(name)
            return profiles
        except (ValueError, TypeError, UnicodeError, OSError, RuntimeError, RecursionError):
            raise ConfigurationError(
                "Invalid code launch.json: use version 1 and up to 128 configurations with "
                "unique names, existing absolute workspaceFolder directories and nonempty "
                "command argument arrays."
            ) from None

    @staticmethod
    def _text(value: object) -> bool:
        return (
            isinstance(value, str)
            and bool(value.strip())
            and len(value) <= 4096
            and "\x00" not in value
        )
