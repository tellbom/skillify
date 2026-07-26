#!/usr/bin/env python3
"""Safely stage source for the standalone GitNexus visualizer.

This helper is deliberately independent from ``skillify.codemap``. It accepts
approved ZIP archives or credential-free HTTP(S) Git URLs and atomically
creates one repository directory below a configured source root.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

REPOSITORY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DEFAULT_MAX_FILES = 50_000
DEFAULT_MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
DEFAULT_GIT_TIMEOUT_SECONDS = 300
COPY_CHUNK_BYTES = 1024 * 1024


class ImportFailure(Exception):
    """The requested source could not be imported safely."""


def validate_repository_id(value: str) -> str:
    if value in {".", ".."} or not REPOSITORY_ID.fullmatch(value):
        raise ImportFailure("repository ID must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}")
    return value


def _destination(source_root: Path, repository_id: str) -> tuple[Path, Path]:
    root = source_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / validate_repository_id(repository_id)
    if target.exists():
        raise ImportFailure(f"repository ID already exists: {repository_id}")
    return root, target


def _safe_zip_members(
    archive: zipfile.ZipFile,
    *,
    max_files: int,
    max_uncompressed_bytes: int,
) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > max_files:
        raise ImportFailure(
            f"ZIP contains too many entries: {len(members)} > {max_files}"
        )
    total_size = sum(member.file_size for member in members)
    if total_size > max_uncompressed_bytes:
        raise ImportFailure(
            f"ZIP expands beyond the allowed size: {total_size} > {max_uncompressed_bytes}"
        )
    for member in members:
        path = PurePosixPath(member.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ImportFailure(
                f"ZIP member escapes the destination: {member.filename}"
            )
        if any(part.lower() in {".git", ".gitnexus"} for part in path.parts):
            raise ImportFailure(
                f"ZIP contains reserved repository metadata: {member.filename}"
            )
        file_type = (member.external_attr >> 16) & 0o170000
        if file_type == stat.S_IFLNK:
            raise ImportFailure(f"ZIP symlinks are not allowed: {member.filename}")
        if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise ImportFailure(f"ZIP special files are not allowed: {member.filename}")
    return members


def import_zip(
    source_root: Path,
    repository_id: str,
    archive_path: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> Path:
    if max_files <= 0 or max_uncompressed_bytes <= 0:
        raise ImportFailure("ZIP limits must be positive integers")
    root, target = _destination(source_root, repository_id)
    try:
        archive_path = archive_path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ImportFailure(f"ZIP import failed: {exc}") from exc
    staging = Path(tempfile.mkdtemp(prefix=f".{repository_id}-", dir=root))
    written = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = _safe_zip_members(
                archive,
                max_files=max_files,
                max_uncompressed_bytes=max_uncompressed_bytes,
            )
            for member in members:
                relative = PurePosixPath(member.filename.replace("\\", "/"))
                if not relative.parts:
                    continue
                output = staging.joinpath(*relative.parts)
                if member.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, output.open("xb") as destination:
                    while chunk := source.read(COPY_CHUNK_BYTES):
                        written += len(chunk)
                        if written > max_uncompressed_bytes:
                            raise ImportFailure(
                                "ZIP exceeded the allowed size while extracting"
                            )
                        destination.write(chunk)
        if not any(staging.iterdir()):
            raise ImportFailure("ZIP does not contain any source files")
        staging.replace(target)
        return target
    except (OSError, zipfile.BadZipFile) as exc:
        raise ImportFailure(f"ZIP import failed: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _allowed_hosts(value: str) -> frozenset[str] | None:
    hosts = frozenset(item.strip().lower() for item in value.split(",") if item.strip())
    return None if not hosts or "*" in hosts else hosts


def validated_git_url(url: str, allowed_hosts: frozenset[str] | None) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ImportFailure("Git URL must use http or https")
    if not parsed.hostname:
        raise ImportFailure("Git URL must contain a host")
    if allowed_hosts is not None and parsed.hostname.lower() not in allowed_hosts:
        raise ImportFailure("Git URL host is not approved")
    if parsed.username is not None or parsed.password is not None:
        raise ImportFailure("credentials embedded in Git URLs are not allowed")
    if parsed.query:
        raise ImportFailure("Git URL query parameters are not allowed")
    if parsed.fragment:
        raise ImportFailure("Git URL fragments are not allowed")
    return url


def import_git(
    source_root: Path,
    repository_id: str,
    url: str,
    *,
    allowed_hosts: frozenset[str] | None,
    branch: str | None = None,
    timeout_seconds: int = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> Path:
    root, target = _destination(source_root, repository_id)
    safe_url = validated_git_url(url, allowed_hosts)
    staging = Path(tempfile.mkdtemp(prefix=f".{repository_id}-", dir=root))
    shutil.rmtree(staging)
    command = [
        "git",
        "-c",
        "credential.helper=",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "http.followRedirects=false",
        "clone",
        "--depth",
        "1",
        "--no-tags",
    ]
    if branch:
        if branch.startswith("-") or any(character.isspace() for character in branch):
            raise ImportFailure("Git branch name is invalid")
        command.extend(["--branch", branch])
    command.extend(["--", safe_url, str(staging)])
    environment = {
        **os.environ,
        "GIT_ASKPASS": "/bin/false",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_LFS_SKIP_SMUDGE": "1",
    }
    try:
        subprocess.run(
            command,
            check=True,
            timeout=timeout_seconds,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        if (staging / ".gitnexus").exists() or (staging / ".gitnexus").is_symlink():
            raise ImportFailure("Git repository contains a reserved .gitnexus path")
        staging.replace(target)
        return target
    except subprocess.TimeoutExpired as exc:
        raise ImportFailure(
            f"Git import timed out after {timeout_seconds} seconds"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        summary = detail[-1] if detail else "git clone failed"
        raise ImportFailure(f"Git import failed: {summary}") from exc
    except OSError as exc:
        raise ImportFailure(f"Git import failed: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="Root containing isolated source directories",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    zip_parser = subparsers.add_parser("zip", help="Import an approved ZIP archive")
    zip_parser.add_argument("repository_id")
    zip_parser.add_argument("archive", type=Path)
    zip_parser.add_argument(
        "--max-files",
        type=int,
        default=int(os.environ.get("GITNEXUS_IMPORT_MAX_FILES", DEFAULT_MAX_FILES)),
    )
    zip_parser.add_argument(
        "--max-bytes",
        type=int,
        default=int(
            os.environ.get(
                "GITNEXUS_IMPORT_MAX_UNCOMPRESSED_BYTES",
                DEFAULT_MAX_UNCOMPRESSED_BYTES,
            )
        ),
    )

    git_parser = subparsers.add_parser("git", help="Clone an approved public Git URL")
    git_parser.add_argument("repository_id")
    git_parser.add_argument("url")
    git_parser.add_argument("--branch")
    git_parser.add_argument(
        "--allowed-hosts",
        default=os.environ.get("GITNEXUS_ALLOWED_GIT_HOSTS", ""),
    )
    git_parser.add_argument(
        "--timeout",
        type=int,
        default=int(
            os.environ.get(
                "GITNEXUS_GIT_TIMEOUT_SECONDS",
                DEFAULT_GIT_TIMEOUT_SECONDS,
            )
        ),
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.action == "zip":
            target = import_zip(
                arguments.source_root,
                arguments.repository_id,
                arguments.archive,
                max_files=arguments.max_files,
                max_uncompressed_bytes=arguments.max_bytes,
            )
        else:
            target = import_git(
                arguments.source_root,
                arguments.repository_id,
                arguments.url,
                allowed_hosts=_allowed_hosts(arguments.allowed_hosts),
                branch=arguments.branch,
                timeout_seconds=arguments.timeout,
            )
    except ImportFailure as exc:
        print(f"[gitnexus-import] ERROR: {exc}", file=os.sys.stderr)
        return 1
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
