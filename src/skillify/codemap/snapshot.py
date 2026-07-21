"""Endpoint-side codemap snapshot packer (P1-2): committed HEAD -> tar+SHA256.

Independent of the task-dispatch protocol (`skillctl codemap snapshot` is a
standalone Phase-1 entry point) and of the human GitNexus visualizer
(`skillify.codemap.visualizer`). Packs only git-tracked files at a clean HEAD.

Deliberately stdlib-only (duplicates the small reproducible-tar/checksum
primitives from `skillify.packaging.pack` rather than importing them): that
module pulls in `skillify.mcp`/`skillify.agent`, which import POSIX-only
modules (e.g. `fcntl`) at module scope, making this file unimportable on the
endpoint's Windows dev tooling. `pack_skill` itself is not reusable regardless
— it excludes `.git` and requires a `skill.yaml` manifest.
"""

from __future__ import annotations

import gzip
import hashlib
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path


class SnapshotError(Exception):
    pass


@dataclass
class SnapshotResult:
    workspace: Path
    commit: str
    tarball_path: Path
    sha256: str
    size_bytes: int
    file_count: int


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False,
    )


def _resolve_clean_head(workspace: Path) -> str:
    status = _run_git(["status", "--porcelain"], cwd=workspace)
    if status.returncode != 0:
        raise SnapshotError(f"workspace is not a git repository: {status.stderr.strip()}")
    if status.stdout.strip():
        raise SnapshotError("workspace has uncommitted changes; snapshot requires a clean workspace")

    head = _run_git(["rev-parse", "HEAD"], cwd=workspace)
    if head.returncode != 0:
        raise SnapshotError(f"failed to resolve workspace HEAD commit: {head.stderr.strip()}")
    return head.stdout.strip()


def _list_tracked_files(workspace: Path) -> list[Path]:
    result = _run_git(["ls-files", "-z"], cwd=workspace)
    if result.returncode != 0:
        raise SnapshotError(f"failed to list tracked files: {result.stderr.strip()}")
    return sorted(workspace / part for part in result.stdout.split("\0") if part)


def _normalized_tarinfo(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
    tarinfo.mtime = 0
    tarinfo.uid = 0
    tarinfo.gid = 0
    tarinfo.uname = ""
    tarinfo.gname = ""
    is_executable = bool(tarinfo.mode & 0o111)
    tarinfo.mode = 0o755 if is_executable else 0o644
    return tarinfo


def _build_tarball(workspace: Path, files: list[Path], dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for f in files:
                    arcname = f.relative_to(workspace).as_posix()
                    tar.add(f, arcname=arcname, filter=_normalized_tarinfo, recursive=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot(workspace: Path, output_dir: Path) -> SnapshotResult:
    """Package the committed HEAD (git-tracked files only) of `workspace` into `output_dir`."""
    workspace = Path(workspace)
    commit = _resolve_clean_head(workspace)
    files = _list_tracked_files(workspace)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tarball_path = output_dir / f"codemap-snapshot-{commit}.tar.gz"
    _build_tarball(workspace, files, tarball_path)
    digest = _sha256_file(tarball_path)

    return SnapshotResult(
        workspace=workspace,
        commit=commit,
        tarball_path=tarball_path,
        sha256=digest,
        size_bytes=tarball_path.stat().st_size,
        file_count=len(files),
    )
