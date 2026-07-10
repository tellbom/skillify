"""Safe tarball extraction — guards against path traversal in untrusted artifacts (T1.4, PLAN §6.2)."""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path

# `filter="data"` (PEP 706) landed as a backport in 3.8.17/3.9.17/3.10.12/3.11.4/3.12+.
# `requires-python = ">=3.10"` doesn't guarantee a patch version that has it (F5), so this
# module does its own equivalent vetting (symlink/hardlink/device rejection + path-escape
# check) unconditionally and only *additionally* asks tarfile for the "data" filter when
# available, instead of depending on it for the core safety guarantee.
_HAS_DATA_FILTER = hasattr(tarfile, "data_filter")


class ChecksumMismatch(Exception):
    def __init__(self, path: Path, expected: str, actual: str):
        super().__init__(f"{path}: expected sha256={expected}, got {actual}")
        self.path = path
        self.expected = expected
        self.actual = actual


class UnsafeArchive(Exception):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(tarball_path: Path, expected_sha256: str) -> None:
    actual = sha256_file(tarball_path)
    if actual != expected_sha256:
        raise ChecksumMismatch(tarball_path, expected_sha256, actual)


def _is_within_directory(directory: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def safe_extract(tarball_path: Path, dest_dir: Path) -> None:
    """Extract `tarball_path` into `dest_dir`, refusing any member whose resolved
    path would land outside `dest_dir` (path traversal / zip-slip style attack),
    any symlink/hardlink, and any device/fifo special file."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball_path, "r:gz") as tar:
        for member in tar.getmembers():
            if member.issym() or member.islnk():
                raise UnsafeArchive(f"{member.name}: symlinks/hardlinks are not allowed in skill artifacts")
            if member.isdev():
                raise UnsafeArchive(f"{member.name}: device/fifo special files are not allowed in skill artifacts")
            member_path = dest_dir / member.name
            if not _is_within_directory(dest_dir, member_path):
                raise UnsafeArchive(f"{member.name}: escapes the extraction directory")
        if _HAS_DATA_FILTER:
            tar.extractall(dest_dir, filter="data")
        else:  # pragma: no cover - only exercised on very old patch releases
            tar.extractall(dest_dir)
