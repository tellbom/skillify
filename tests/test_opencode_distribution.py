from __future__ import annotations

import hashlib, json, subprocess
from pathlib import Path

import pytest

from skillify.install.opencode_distribution import (
    ArtifactCorrupt, ManifestInvalid, load_manifest, select_artifact,
    validate_manifest, verify_artifact,
)

MANIFEST = Path("infra/offline/opencode-manifest.json")


def _data(uri="file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64.tar.gz"):
    return {"schemaVersion": 1, "opencodeVersion": "1.15.11", "skillctlVersion": "0.1.0", "artifacts": [{
        "version": "1.15.11", "skillctlVersion": "0.1.0", "os": "linux", "arch": "x86_64",
        "libc": "glibc", "cpu": "avx2", "sha256": "a" * 64, "license": "MIT",
        "sourceUrl": "https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-x64.tar.gz",
        "intranetUri": uri,
    }]}


def test_repository_manifest_matches_schema_and_has_no_latest() -> None:
    data = load_manifest(MANIFEST); validate_manifest(data)
    assert "latest" not in json.dumps(data).lower()
    assert len(data["artifacts"]) == 6


def test_selects_only_exact_version_and_platform() -> None:
    artifact = select_artifact(_data(), version="1.15.11", os_name="linux", arch="x86_64", libc="glibc", cpu="avx2")
    assert artifact.version == "1.15.11" and artifact.intranet_uri.startswith("file:///")
    with pytest.raises(ManifestInvalid, match="no exact artifact"):
        select_artifact(_data(), version="1.15.12", os_name="linux", arch="x86_64", libc="glibc", cpu="avx2")


@pytest.mark.parametrize("uri", ["https://mirror.example/opencode.tgz", "forgejo://artifacts/opencode.tgz", "file://host/path.tgz", "file:relative.tgz"])
def test_rejects_every_non_local_or_non_absolute_runtime_uri(uri: str) -> None:
    with pytest.raises(ManifestInvalid, match="intranetUri"):
        validate_manifest(_data(uri))


@pytest.mark.parametrize(("field", "value", "message"), [
    (
        "sourceUrl",
        "https://github.com/attacker/releases/download/v1.15.11/opencode-linux-x64.tar.gz",
        "sourceUrl",
    ),
    (
        "intranetUri",
        "file:///opt/skillify/offline/opencode/v1.15.11/../../outside.tar.gz",
        "intranetUri",
    ),
])
def test_rejects_noncanonical_source_and_bundle_uri(field: str, value: str, message: str) -> None:
    data = _data()
    data["artifacts"][0][field] = value
    with pytest.raises(ManifestInvalid, match=message):
        validate_manifest(data)


def test_verifies_matching_sha256_and_rejects_corruption(tmp_path: Path) -> None:
    path = tmp_path / "opencode.tar.gz"; path.write_bytes(b"official bytes")
    data = _data(); data["artifacts"][0]["sha256"] = hashlib.sha256(b"official bytes").hexdigest()
    artifact = select_artifact(data, version="1.15.11", os_name="linux", arch="x86_64", libc="glibc", cpu="avx2")
    verify_artifact(path, artifact)
    path.write_bytes(b"corrupt")
    with pytest.raises(ArtifactCorrupt): verify_artifact(path, artifact)


def test_doctor_verifies_manifest_platform_version_and_checksum(tmp_path: Path) -> None:
    from skillify.cli.doctor_cmd import _check_opencode_distribution
    payload = b"approved opencode bundle"
    data = _data(); data["artifacts"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps(data), encoding="utf-8")
    artifact_root = tmp_path / "artifacts"; artifact_root.mkdir()
    (artifact_root / "opencode-linux-x64.tar.gz").write_bytes(payload)
    checks = _check_opencode_distribution(
        manifest_path=manifest,
        artifact_root=artifact_root,
        platform_detector=lambda: ("linux", "x86_64", "glibc", "avx2"),
        version_runner=lambda argv: "1.15.11\n",
    )
    assert [check.name for check in checks] == [
        "opencode-manifest", "opencode-platform", "opencode-version", "opencode-checksum",
    ]
    assert all(check.ok for check in checks)


def test_doctor_reports_version_subprocess_failure(tmp_path: Path) -> None:
    from skillify.cli.doctor_cmd import _check_opencode_distribution
    payload = b"approved opencode bundle"
    data = _data(); data["artifacts"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps(data), encoding="utf-8")
    artifact_root = tmp_path / "artifacts"; artifact_root.mkdir()
    (artifact_root / "opencode-linux-x64.tar.gz").write_bytes(payload)

    def timeout(argv: list[str]) -> str:
        raise subprocess.TimeoutExpired(argv, 5)

    checks = _check_opencode_distribution(
        manifest_path=manifest,
        artifact_root=artifact_root,
        platform_detector=lambda: ("linux", "x86_64", "glibc", "avx2"),
        version_runner=timeout,
    )

    assert len(checks) == 1
    assert checks[0].ok is False
