"""Dedicated central code profiles; loading never writes or executes commands."""

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from debugpilot.core.exceptions import ConfigurationError
from debugpilot.storage.config import config_path

ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
MAX_ENV_ENTRIES = 256
MAX_ENV_VALUE = 32_768
MAX_ENV_FILE_BYTES = 256 * 1024


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
    # Extra variables for Run and Debug: `env` pairs and an `envFile` relative to root.
    env: tuple[tuple[str, str], ...] = ()
    env_file: str | None = None

    @property
    def attach(self) -> RemoteAttach | None:
        return self.go_attach or self.python_attach


def _env_value(value: object) -> bool:
    return isinstance(value, str) and len(value) <= MAX_ENV_VALUE and "\x00" not in value


def parse_env_settings(entry: dict) -> tuple[tuple[tuple[str, str], ...], str | None]:
    """Validate a profile's optional `env` map and `envFile` path; values are never shown."""
    env = entry.get("env", {})
    if (not isinstance(env, dict) or len(env) > MAX_ENV_ENTRIES
            or any(not isinstance(key, str) or not ENV_NAME.match(key) or not _env_value(value)
                   for key, value in env.items())):
        raise ConfigurationError(
            "Invalid env: use a map of variable names (letters, digits, underscore; not "
            "starting with a digit) to text values."
        )
    env_file = entry.get("envFile")
    if env_file is not None:
        relative = PurePosixPath(env_file) if isinstance(env_file, str) else None
        if (not CodeProjectStore._text(env_file) or relative.is_absolute()
                or Path(env_file).is_absolute() or ".." in Path(env_file).parts):
            raise ConfigurationError(
                "Invalid envFile: use a path relative to the workspaceFolder, without '..'."
            )
    return tuple(env.items()), env_file


def parse_env_file(text: str) -> dict[str, str]:
    """KEY=VALUE lines, `#` comments, optional `export` and quotes; no expansion."""
    variables = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or not ENV_NAME.match(name):
            # Only the line number: the line may hold a secret.
            raise ConfigurationError(f"Invalid envFile line {number}: use NAME=value.")
        if value[:1] in {'"', "'"}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigurationError(
                    f"Invalid envFile line {number}: a quoted value must close its quote."
                )
            value = value[1:-1]
        if not _env_value(value):
            raise ConfigurationError(f"Invalid envFile line {number}: the value is too long.")
        variables[name] = value
    return variables


def profile_variables(profile) -> dict[str, str]:
    """Only the profile's own variables: `envFile`, then `env` on top."""
    env, env_file = getattr(profile, "env", ()), getattr(profile, "env_file", None)
    variables = {}
    if env_file is not None:
        variables.update(_read_env_file(Path(profile.root), env_file))
    variables.update(env)
    return variables


def profile_environment(profile) -> dict[str, str] | None:
    """The full environment for Run/Debug, or None to inherit it unchanged.

    The inherited environment is overridden by `envFile`, which `env` overrides in turn.
    The file is read on every run, so edits apply without reloading the profiles.
    """
    if not getattr(profile, "env", ()) and getattr(profile, "env_file", None) is None:
        return None
    return {**os.environ, **profile_variables(profile)}


def _read_env_file(root: Path, env_file: str) -> dict[str, str]:
    path = root / env_file
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_ENV_FILE_BYTES + 1)
    except FileNotFoundError:
        raise ConfigurationError(f"envFile not found: {env_file}") from None
    except OSError:
        message = f"Cannot read envFile {env_file}; check permissions."
        raise ConfigurationError(message) from None
    if len(data) > MAX_ENV_FILE_BYTES:
        raise ConfigurationError(f"envFile {env_file} exceeds 256 KiB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        raise ConfigurationError(f"envFile {env_file} is not UTF-8 text.") from None
    return parse_env_file(text)


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
                env, env_file = parse_env_settings(entry)
                if attach is not None and (env or env_file is not None):
                    raise ConfigurationError(
                        "env and envFile apply to profiles that run a command; an attach "
                        "target keeps the environment of its container."
                    )
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
                                            node_debug, go_attach, python_attach,
                                            env, env_file))
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
