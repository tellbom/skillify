"""Tests for the P1-3 server-side upload verification primitives (safe extract, checksum, task_id)."""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from skillify.codemap.upload_verify import (
    UploadVerifyError,
    safe_extract,
    sha256_file,
    validate_task_id,
    verify_checksum,
)


def _make_tar(dest: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(dest, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_validate_task_id_accepts_safe_charset() -> None:
    assert validate_task_id("task-123_ABC") == "task-123_ABC"


@pytest.mark.parametrize(
    "bad_id",
    ["../etc", "a/b", "", "a" * 65, "-leading-dash", ".hidden", "task id"],
)
def test_validate_task_id_rejects_unsafe_values(bad_id: str) -> None:
    with pytest.raises(UploadVerifyError):
        validate_task_id(bad_id)


def test_verify_checksum_accepts_matching_digest(tmp_path: Path) -> None:
    path = tmp_path / "f.tar.gz"
    path.write_bytes(b"hello world")
    digest = hashlib.sha256(b"hello world").hexdigest()

    verify_checksum(path, digest)  # must not raise


def test_verify_checksum_rejects_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "f.tar.gz"
    path.write_bytes(b"hello world")

    with pytest.raises(UploadVerifyError, match="checksum"):
        verify_checksum(path, "0" * 64)


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"some bytes here")
    assert sha256_file(path) == hashlib.sha256(b"some bytes here").hexdigest()


def test_safe_extract_extracts_normal_files(tmp_path: Path) -> None:
    tar_path = tmp_path / "snap.tar.gz"
    _make_tar(tar_path, {"main.py": b"print(1)\n", "sub/dir/file.txt": b"data\n"})
    dest = tmp_path / "dest"

    extracted = safe_extract(tar_path, dest)

    assert sorted(extracted) == ["main.py", "sub/dir/file.txt"]
    assert (dest / "main.py").read_bytes() == b"print(1)\n"
    assert (dest / "sub" / "dir" / "file.txt").read_bytes() == b"data\n"


def test_safe_extract_rejects_dotdot_traversal(tmp_path: Path) -> None:
    tar_path = tmp_path / "evil.tar.gz"
    _make_tar(tar_path, {"../../etc/passwd": b"pwned\n"})
    dest = tmp_path / "dest"

    with pytest.raises(UploadVerifyError, match="traversal"):
        safe_extract(tar_path, dest)
    assert not (tmp_path / "etc").exists()


def test_safe_extract_rejects_absolute_path_member(tmp_path: Path) -> None:
    tar_path = tmp_path / "evil2.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        info = tarfile.TarInfo(name="/etc/passwd")
        data = b"pwned\n"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    dest = tmp_path / "dest"

    with pytest.raises(UploadVerifyError):
        safe_extract(tar_path, dest)


def test_safe_extract_rejects_symlink_member(tmp_path: Path) -> None:
    tar_path = tmp_path / "evil3.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        info = tarfile.TarInfo(name="link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    dest = tmp_path / "dest"

    with pytest.raises(UploadVerifyError, match="symlink"):
        safe_extract(tar_path, dest)
