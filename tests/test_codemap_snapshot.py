"""Tests for the P1-2 endpoint-side codemap snapshot packer (git HEAD -> tar+SHA256)."""

from __future__ import annotations

import hashlib
import subprocess
import tarfile
from pathlib import Path

import pytest

from skillify.codemap.snapshot import SnapshotError, build_snapshot


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(["init"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    _git(["add", "main.py"], cwd=repo)
    _git(["commit", "-m", "initial"], cwd=repo)
    return _git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()


def test_build_snapshot_rejects_dirty_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "main.py").write_text("print('changed')\n", encoding="utf-8")

    with pytest.raises(SnapshotError, match="uncommitted"):
        build_snapshot(repo, tmp_path / "out")


def test_build_snapshot_rejects_non_git_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "not-a-repo"
    workspace.mkdir()

    with pytest.raises(SnapshotError, match="git"):
        build_snapshot(workspace, tmp_path / "out")


def test_build_snapshot_packs_only_tracked_files_with_verifiable_checksum(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    commit = _init_repo(repo)
    (repo / ".gitignore").write_text("ignored.txt\n.venv/\n", encoding="utf-8")
    _git(["add", ".gitignore"], cwd=repo)
    _git(["commit", "-m", "add gitignore"], cwd=repo)
    (repo / "ignored.txt").write_text("should not be packed\n", encoding="utf-8")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "pyvenv.cfg").write_text("x\n", encoding="utf-8")
    commit = _git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()

    result = build_snapshot(repo, tmp_path / "out")

    assert result.commit == commit
    assert result.tarball_path.is_file()
    assert result.sha256 == _sha256_file(result.tarball_path)
    with tarfile.open(result.tarball_path, "r:gz") as tar:
        names = sorted(tar.getnames())
    assert names == [".gitignore", "main.py"]
    assert result.file_count == 2


def test_build_snapshot_is_reproducible(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    result1 = build_snapshot(repo, tmp_path / "out1")
    result2 = build_snapshot(repo, tmp_path / "out2")

    assert result1.sha256 == result2.sha256
