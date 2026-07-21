"""P1-3: server-side upload-verification primitives (checksum + safe tar extraction).

Pure-stdlib on purpose: importing `skillify.packaging.pack` here would drag in
`skillify.mcp`/`skillify.agent`, which import POSIX-only modules (e.g. `fcntl`)
at module scope, making this file unimportable on the endpoint's dev tooling.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import tarfile
from pathlib import Path
from typing import BinaryIO

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class UploadVerifyError(Exception):
    pass


def validate_task_id(task_id: str) -> str:
    if not _TASK_ID_RE.match(task_id):
        raise UploadVerifyError(f"invalid task_id: {task_id!r}")
    return task_id


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: Path, expected_sha256: str) -> None:
    actual = sha256_file(path)
    if not hmac.compare_digest(actual, expected_sha256.strip().lower()):
        raise UploadVerifyError("checksum mismatch")


def _resolve_member_target(member: tarfile.TarInfo, dest_dir: Path) -> Path:
    if member.issym() or member.islnk():
        raise UploadVerifyError(f"unsafe tar member (symlink/hardlink): {member.name}")
    if Path(member.name).is_absolute():
        raise UploadVerifyError(f"unsafe tar member (absolute path): {member.name}")

    target = (dest_dir / member.name).resolve()
    if target != dest_dir and dest_dir not in target.parents:
        raise UploadVerifyError(f"path traversal attempt: {member.name}")
    return target


def safe_extract(tar_path: Path, dest_dir: Path) -> list[str]:
    """Extract only regular files/directories from `tar_path` into `dest_dir`.

    Rejects symlinks/hardlinks, absolute paths, and `..`-style traversal before
    extracting anything (validate-then-extract, not extract-then-check).
    """
    dest_dir = Path(dest_dir)
    fh: BinaryIO
    with tarfile.open(tar_path, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            _resolve_member_target(member, dest_dir)

        dest_dir.mkdir(parents=True, exist_ok=True)
        extracted = [m.name for m in members if m.isfile()]
        for member in members:
            tar.extract(member, dest_dir, filter="data")

    return sorted(extracted)
