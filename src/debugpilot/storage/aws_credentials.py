"""Refresh AWS session credentials into profile dotenv files without exposing them.

The AWS CLI resolves the credentials (``aws configure export-credentials``), the same
source used by ``make refresh-aws-credentials`` in the project repositories. Only the
three credential keys are replaced; every other line of each file is preserved.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from debugpilot.core.exceptions import DebugPilotError

AWS_PROFILE_NAME = re.compile(r"^[A-Za-z0-9_.@+-]{1,128}$")
CREDENTIAL_VALUE = re.compile(r"^[A-Za-z0-9/+=_.-]{1,4096}$")
CREDENTIAL_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
MAX_ENV_BYTES = 1024 * 1024
EXPORT_TIMEOUT_SECONDS = 60
AWS_CREDENTIAL_FIELDS = {"envFiles", "profile"}


def aws_file_paths() -> tuple[Path, Path]:
    """The AWS CLI's config and credentials files, honoring its environment overrides."""
    home = Path.home() / ".aws"
    config = os.environ.get("AWS_CONFIG_FILE") or str(home / "config")
    credentials = os.environ.get("AWS_SHARED_CREDENTIALS_FILE") or str(home / "credentials")
    return Path(config).expanduser(), Path(credentials).expanduser()


class CredentialError(DebugPilotError):
    """A safe credential failure message; it never contains credential values."""


@dataclass(frozen=True)
class AwsCredentialsTarget:
    """Validated destination files for one launch profile."""

    env_files: tuple[Path, ...]
    aws_profile: str | None = None


@dataclass(frozen=True)
class _Credentials:
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    session_token: str | None = field(default=None, repr=False)
    expiration: str | None = None

    def values(self) -> dict[str, str | None]:
        return {
            "AWS_ACCESS_KEY_ID": self.access_key_id,
            "AWS_SECRET_ACCESS_KEY": self.secret_access_key,
            "AWS_SESSION_TOKEN": self.session_token,
        }


@dataclass
class RefreshResult:
    updated_files: list[Path] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    expirations: dict[str, str] = field(default_factory=dict)


def parse_aws_credentials_field(value: Any) -> tuple[tuple[str, ...], str | None] | None:
    """Validate the raw ``awsCredentials`` shape; paths are resolved by the caller."""
    if not isinstance(value, dict) or not value or set(value) - AWS_CREDENTIAL_FIELDS:
        return None
    files = value.get("envFiles")
    if (
        not isinstance(files, list)
        or not 1 <= len(files) <= 16
        or any(not isinstance(item, str) or not item for item in files)
    ):
        return None
    profile = value.get("profile")
    if profile is not None and (
        not isinstance(profile, str) or not AWS_PROFILE_NAME.fullmatch(profile)
    ):
        return None
    return tuple(files), profile


Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _default_runner(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        timeout=EXPORT_TIMEOUT_SECONDS,
        check=False,
    )


def export_credentials(aws_profile: str | None, *, runner: Runner | None = None) -> _Credentials:
    """Ask the AWS CLI for the current credentials of one profile (no shell, no temp file)."""
    executable = shutil.which("aws")
    if executable is None:
        raise CredentialError("AWS CLI is not installed or not on PATH.")
    arguments = [executable, "configure", "export-credentials", "--format", "process"]
    if aws_profile is not None:
        arguments.extend(("--profile", aws_profile))
    try:
        result = (runner or _default_runner)(arguments)
    except subprocess.TimeoutExpired:
        raise CredentialError("AWS CLI timed out exporting credentials.") from None
    except OSError:
        raise CredentialError("Cannot run the AWS CLI.") from None
    login = "aws sso login" + (f" --profile {aws_profile}" if aws_profile else "")
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        reason = detail[-1][:200] if detail else f"exit {result.returncode}"
        raise CredentialError(f"AWS CLI could not export credentials ({reason}). Run `{login}`.")
    try:
        payload = json.loads(result.stdout)
        access = payload["AccessKeyId"]
        secret = payload["SecretAccessKey"]
        token = payload.get("SessionToken")
        expiration = payload.get("Expiration")
        if not all(
            isinstance(item, str) and CREDENTIAL_VALUE.fullmatch(item)
            for item in (
                access,
                secret,
            )
        ):
            raise ValueError
        if token is not None and (
            not isinstance(token, str) or not CREDENTIAL_VALUE.fullmatch(token)
        ):
            raise ValueError
        if expiration is not None and not isinstance(expiration, str):
            expiration = None
    except (ValueError, KeyError, TypeError):
        raise CredentialError("AWS CLI returned credentials in an unexpected format.") from None
    return _Credentials(access, secret, token, expiration[:64] if expiration else None)


_KEY_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def render_env_file(original: str, credentials: _Credentials) -> str:
    """Replace only the credential keys; missing keys are appended, others kept verbatim."""
    values = credentials.values()
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines()
    written: set[str] = set()
    output = []
    for line in lines:
        match = _KEY_LINE.match(line)
        key = match.group(1) if match else None
        if key in values:
            if key in written or values[key] is None:
                continue  # drop duplicates and a stale token when none is issued
            output.append(f"{key}={values[key]}")
            written.add(key)
        else:
            output.append(line)
    for key in CREDENTIAL_KEYS:
        if key not in written and values[key] is not None:
            output.append(f"{key}={values[key]}")
    return newline.join(output) + newline


def write_env_file(path: Path, credentials: _Credentials) -> None:
    """Atomically rewrite one dotenv file with private permissions."""
    try:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            original = ""
        else:
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise CredentialError(f"{path.name} must be a regular file, not a symlink.")
            if metadata.st_size > MAX_ENV_BYTES:
                raise CredentialError(f"{path.name} is larger than 1 MiB.")
            original = path.read_text(encoding="utf-8")
        content = render_env_file(original, credentials)
        descriptor, temporary = tempfile.mkstemp(prefix=".debugpilot-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
    except CredentialError:
        raise
    except (OSError, UnicodeError):
        raise CredentialError(f"Cannot update {path.name}; check file permissions.") from None


def refresh_targets(
    targets: Iterable[tuple[str, AwsCredentialsTarget]],
    *,
    exporter: Callable[[str | None], _Credentials] = export_credentials,
) -> RefreshResult:
    """Export once per AWS profile and write each distinct file once."""
    result = RefreshResult()
    by_aws_profile: dict[str | None, list[tuple[str, AwsCredentialsTarget]]] = {}
    for name, target in targets:
        by_aws_profile.setdefault(target.aws_profile, []).append((name, target))
    written: dict[Path, str | None] = {}
    for aws_profile, members in by_aws_profile.items():
        label = aws_profile or "default"
        try:
            credentials = exporter(aws_profile)
        except CredentialError as error:
            result.errors.append(f"AWS profile {label}: {error}")
            continue
        if credentials.expiration:
            result.expirations[label] = credentials.expiration
        for name, target in members:
            failed = False
            for path in target.env_files:
                if path in written:
                    if written[path] != aws_profile:
                        result.errors.append(
                            f"{name}: {path.name} is shared by different AWS profiles."
                        )
                        failed = True
                    continue
                try:
                    write_env_file(path, credentials)
                except CredentialError as error:
                    result.errors.append(f"{name}: {error}")
                    failed = True
                    continue
                written[path] = aws_profile
                result.updated_files.append(path)
            if not failed:
                result.profiles.append(name)
    return result
