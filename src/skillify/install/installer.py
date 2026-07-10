"""Core single-skill install primitive: resolve -> download -> verify -> extract ->
venv+deps -> lock (T1.4). Skill-to-skill dependency recursion lives in `dependencies.py` (T1.5);
agent-target projection lives in `projector.py` (T1.4a) and is layered on top by the CLI.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from skillify.common.config import SkillifyConfig
from skillify.common.identifier import parse_identifier
from skillify.install.extract import ChecksumMismatch, safe_extract, sha256_file, verify_checksum
from skillify.install.lock import SkillLock, read_lock, write_lock
from skillify.install.resolver import ResolveError, resolve_release_artifact
from skillify.install.venv import ensure_venv, install_python_deps
from skillify.publish.forgejo_client import ForgejoClient, ForgejoError
from skillify.validator import validate_skill_dir


class InstallError(Exception):
    pass


def _download_via_source_override(source: str, version: str | None, tmp_dir: Path) -> tuple[Path, str]:
    """Download a tarball directly from a URL (mainly for tests without a live Forgejo).
    Requires an explicit version (no release metadata to infer it from) and a sibling
    `.sha256` file at the same base name for integrity verification."""
    import requests

    if version is None:
        raise InstallError("--source requires an explicit '@version' in the identifier")
    if not source.endswith(".tar.gz"):
        raise InstallError(f"--source must point at a .tar.gz artifact, got {source!r}")

    tarball_path = tmp_dir / "artifact.tar.gz"
    resp = requests.get(source, timeout=15)
    if resp.status_code != 200:
        raise InstallError(f"failed to download {source}: HTTP {resp.status_code}")
    tarball_path.write_bytes(resp.content)

    checksum_url = source[: -len(".tar.gz")] + ".sha256"
    resp = requests.get(checksum_url, timeout=15)
    if resp.status_code != 200:
        raise InstallError(f"failed to download checksum sidecar {checksum_url}: HTTP {resp.status_code}")
    expected_sha256 = resp.text.split()[0]

    return tarball_path, expected_sha256


def _download_via_forgejo(
    cfg: SkillifyConfig, namespace: str, name: str, version: str | None, tmp_dir: Path
) -> tuple[Path, str, str]:
    if not cfg.forgejo_url or not cfg.forgejo_token:
        raise InstallError(
            "forgejo_url / forgejo_token not configured — run `skillctl doctor` to see what's missing, "
            "or pass --source for a direct artifact URL."
        )
    org = cfg.forgejo_org or namespace
    client = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    try:
        artifact = resolve_release_artifact(client, org, namespace, name, version)
        tarball_path = tmp_dir / "artifact.tar.gz"
        client.download(artifact.tarball_url, tarball_path)
        if artifact.checksum_url is None:
            raise InstallError(f"{org}/{name}@{artifact.version}: release has no .sha256 asset to verify against")
        checksum_path = tmp_dir / "artifact.sha256"
        client.download(artifact.checksum_url, checksum_path)
        expected_sha256 = checksum_path.read_text(encoding="utf-8").split()[0]
    except (ForgejoError, ResolveError) as exc:
        raise InstallError(str(exc)) from exc
    return tarball_path, expected_sha256, artifact.version


def install_skill(
    identifier: str,
    *,
    cfg: SkillifyConfig,
    source_override: str | None = None,
    install_deps: bool = True,
) -> SkillLock:
    namespace, name, version = parse_identifier(identifier)
    cfg.ensure_dirs()

    tmp_dir = cfg.cache_dir / "tmp" / f"{namespace}__{name}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    try:
        if source_override:
            tarball_path, expected_sha256 = _download_via_source_override(source_override, version, tmp_dir)
            resolved_version = version
            source_label = source_override
        else:
            tarball_path, expected_sha256, resolved_version = _download_via_forgejo(
                cfg, namespace, name, version, tmp_dir
            )
            source_label = f"{cfg.forgejo_url}/{cfg.forgejo_org or namespace}/{name}@v{resolved_version}"

        try:
            verify_checksum(tarball_path, expected_sha256)
        except ChecksumMismatch as exc:
            raise InstallError(str(exc)) from exc

        # C1: extract to a staging dir first and re-verify the artifact's own manifest
        # against what was requested/resolved *before* touching the real install dir —
        # checksum verification only proves the bytes weren't tampered in transit, not
        # that the Release asset actually contains the skill it claims to (a manually
        # crafted/mislabeled Forgejo Release could still pass checksum verification).
        staging_dir = tmp_dir / "staging" / namespace / name
        safe_extract(tarball_path, staging_dir)

        manifest = yaml.safe_load((staging_dir / "skill.yaml").read_text(encoding="utf-8"))
        extracted_namespace = manifest.get("namespace")
        extracted_name = manifest.get("name")
        extracted_version = manifest.get("version")
        if extracted_namespace != namespace or extracted_name != name:
            raise InstallError(
                f"artifact content mismatch: requested {namespace}/{name}, but the extracted "
                f"skill.yaml declares {extracted_namespace}/{extracted_name}"
            )
        if extracted_version != resolved_version:
            raise InstallError(
                f"artifact content mismatch: expected version {resolved_version!r}, but the "
                f"extracted skill.yaml declares version {extracted_version!r}"
            )
        validation = validate_skill_dir(staging_dir, namespace_aware=True)
        if not validation.ok:
            issues = "; ".join(str(i) for i in validation.issues)
            raise InstallError(f"extracted artifact for {namespace}/{name} failed validation: {issues}")

        python_deps = ((manifest.get("dependencies") or {}).get("python")) or []
        skill_deps = ((manifest.get("dependencies") or {}).get("skills")) or []
        declared_targets = manifest.get("targets") or []

        skill_dir = cfg.skills_dir / namespace / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        skill_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging_dir), str(skill_dir))

        venv_path: str | None = None
        if python_deps:
            venv_dir = cfg.venvs_dir / f"{namespace}__{name}"
            ensure_venv(venv_dir)
            if install_deps:
                install_python_deps(venv_dir, python_deps, index_url=cfg.devpi_index_url)
            venv_path = str(venv_dir)

        previous_lock = read_lock(cfg.locks_dir, namespace, name)
        lock = SkillLock(
            namespace=namespace,
            name=name,
            version=resolved_version,
            sha256=expected_sha256,
            source=source_label,
            installedAt=datetime.now(timezone.utc).isoformat(),
            venvPath=venv_path,
            pythonDeps=python_deps,
            skillDeps=skill_deps,
            declaredTargets=declared_targets,
            targets=previous_lock.targets if previous_lock else [],
        )
        write_lock(cfg.locks_dir, lock)
        return lock
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
