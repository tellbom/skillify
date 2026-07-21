"""Deterministic tarball + checksum + artifact-manifest packaging (T1.2)."""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from skillify import __version__
from skillify.mcp.registry import McpArtifact, mcp_artifact_as_dict
from skillify.security.scan import generate_sbom, scan_artifact, write_sbom
from skillify.validator import ValidationResult, validate_skill_dir

_EXCLUDED_DIR_NAMES = {".git", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache"}
_EXCLUDED_FILE_NAMES = {".DS_Store"}


class PackagingError(Exception):
    def __init__(self, result: ValidationResult):
        issues = "\n".join(f"  - {i}" for i in result.issues)
        super().__init__(f"skill failed validation, refusing to package:\n{issues}")
        self.result = result


@dataclass
class PackResult:
    tarball_path: Path
    checksum_path: Path
    artifact_manifest_path: Path
    sbom_path: Path
    sha256: str
    size_bytes: int
    file_count: int
    namespace: str
    name: str
    version: str
    description: str
    author: str | dict
    tags: list[str]
    orchestration: dict


@dataclass
class McpPackResult:
    tarball_path: Path
    checksum_path: Path
    artifact_manifest_path: Path
    sha256: str
    size_bytes: int
    namespace: str
    name: str
    version: str
    artifact: McpArtifact


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDED_DIR_NAMES for part in path.parts) or path.name in _EXCLUDED_FILE_NAMES


def _collect_files(skill_dir: Path) -> list[Path]:
    return sorted(
        (p for p in skill_dir.rglob("*") if p.is_file() and not _is_excluded(p)),
        key=lambda p: p.relative_to(skill_dir).as_posix(),
    )


def _normalized_tarinfo(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
    tarinfo.mtime = 0
    tarinfo.uid = 0
    tarinfo.gid = 0
    tarinfo.uname = ""
    tarinfo.gname = ""
    is_executable = bool(tarinfo.mode & 0o111)
    tarinfo.mode = 0o755 if is_executable else 0o644
    return tarinfo


def build_tarball(skill_dir: Path, dest_path: Path) -> None:
    """Write a byte-reproducible tar.gz of `skill_dir` to `dest_path`.

    Reproducible across repeated runs on the same inputs: sorted file order,
    zeroed mtime/uid/gid/uname/gname, mode normalized to 0644/0755 by
    executable bit. Not claimed to be bit-identical across platforms with
    different gzip implementations — only same-toolchain reproducibility is
    the acceptance bar here (spec: "产物可复现（同输入同 checksum）").
    """
    files = _collect_files(skill_dir)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for f in files:
                    arcname = f.relative_to(skill_dir).as_posix()
                    tar.add(f, arcname=arcname, filter=_normalized_tarinfo, recursive=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack_skill(skill_dir: Path, output_dir: Path) -> PackResult:
    skill_dir = Path(skill_dir)
    manifest_path = skill_dir / "skill.yaml"
    if not manifest_path.is_file():
        # Let validate_skill_dir produce the canonical "file not found" issue.
        result = validate_skill_dir(skill_dir, namespace_aware=False)
        raise PackagingError(result)

    manifest: dict[str, Any] = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    namespace_aware = skill_dir.parent.name == manifest.get("namespace")
    result = validate_skill_dir(skill_dir, namespace_aware=namespace_aware)
    if not result.ok:
        raise PackagingError(result)

    scan = scan_artifact(skill_dir)
    for finding in scan.findings:
        if finding.level.value == "block":
            result.add(f"security:{finding.path}", finding.message)
    if not result.ok:
        raise PackagingError(result)

    namespace, name, version = manifest["namespace"], manifest["name"], manifest["version"]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = f"{namespace}-{name}-{version}"
    tarball_path = output_dir / f"{base}.tar.gz"
    checksum_path = output_dir / f"{base}.sha256"
    artifact_manifest_path = output_dir / f"{base}.artifact.json"
    sbom_path = output_dir / f"{base}.sbom.json"

    build_tarball(skill_dir, tarball_path)
    digest = sha256_file(tarball_path)
    size_bytes = tarball_path.stat().st_size
    file_count = len(_collect_files(skill_dir))

    checksum_path.write_text(f"{digest}  {tarball_path.name}\n", encoding="utf-8")
    write_sbom(generate_sbom(skill_dir, name=f"{namespace}/{name}", version=version), sbom_path)

    artifact_manifest = {
        "artifactSchemaVersion": 1,
        "artifactKind": "skill",
        "namespace": namespace,
        "name": name,
        "version": version,
        "manifestVersion": manifest["manifestVersion"],
        "sha256": digest,
        "sizeBytes": size_bytes,
        "fileCount": file_count,
        "tarball": tarball_path.name,
        "packagedBy": f"skillctl {__version__}",
        "sbom": sbom_path.name,
        "scan": scan.as_dict(),
        "skillManifest": manifest,
    }
    workflow_path = skill_dir / "workflow.yaml"
    if workflow_path.is_file():
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
        if isinstance(workflow, dict):
            artifact_manifest["workflowDefinition"] = {
                key: workflow[key]
                for key in ("id", "delegation", "execution", "replayCases")
                if key in workflow
            }
    artifact_manifest_path.write_text(
        json.dumps(artifact_manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )

    return PackResult(
        tarball_path=tarball_path,
        checksum_path=checksum_path,
        artifact_manifest_path=artifact_manifest_path,
        sbom_path=sbom_path,
        sha256=digest,
        size_bytes=size_bytes,
        file_count=file_count,
        namespace=namespace,
        name=name,
        version=version,
        description=manifest.get("description", ""),
        author=manifest.get("author", ""),
        tags=manifest.get("tags") or [],
        orchestration=manifest.get("orchestration") or {},
    )


def pack_mcp(artifact: McpArtifact, archive_path: Path, output_dir: Path) -> McpPackResult:
    """Package an already-built approved MCP archive without changing its bytes."""
    if type(artifact) is not McpArtifact:
        raise ValueError("artifact must be validated MCP metadata")
    source = Path(archive_path)
    if not source.is_file() or source.is_symlink():
        raise ValueError("MCP archive must be a regular non-symlink file")
    digest = sha256_file(source)
    if not hmac.compare_digest(digest, artifact.checksum):
        raise ValueError("MCP archive checksum does not match immutable metadata")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    base = f"{artifact.namespace}-{artifact.name}-{artifact.coordinate.version}"
    tarball_path = destination / f"{base}.tar.gz"
    checksum_path = destination / f"{base}.sha256"
    artifact_manifest_path = destination / f"{base}.artifact.json"
    if source.resolve() != tarball_path.resolve():
        shutil.copyfile(source, tarball_path)
    checksum_path.write_text(f"{digest}  {tarball_path.name}\n", encoding="utf-8")
    sidecar = {
        "artifactSchemaVersion": 1,
        "artifactKind": "mcp",
        "namespace": artifact.namespace,
        "name": artifact.name,
        "version": artifact.coordinate.version,
        "sha256": digest,
        "sizeBytes": tarball_path.stat().st_size,
        "tarball": tarball_path.name,
        "packagedBy": f"skillctl {__version__}",
        "mcpArtifact": mcp_artifact_as_dict(artifact),
    }
    artifact_manifest_path.write_text(
        json.dumps(sidecar, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return McpPackResult(
        tarball_path=tarball_path,
        checksum_path=checksum_path,
        artifact_manifest_path=artifact_manifest_path,
        sha256=digest,
        size_bytes=tarball_path.stat().st_size,
        namespace=artifact.namespace,
        name=artifact.name,
        version=artifact.coordinate.version,
        artifact=artifact,
    )
