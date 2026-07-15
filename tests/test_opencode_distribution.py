from __future__ import annotations

import hashlib, json, subprocess
from pathlib import Path

import pytest

from skillify.install.opencode_distribution import (
    ArtifactCorrupt, ArtifactNotFound, ManifestInvalid, load_manifest, select_artifact,
    validate_manifest, verify_artifact,
)

MANIFEST = Path("infra/offline/opencode-manifest.json")
RUNBOOK = Path("docs/deployment/offline-opencode.md")


def _data(uri="file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64.tar.gz"):
    return {"schemaVersion": 1, "opencodeVersion": "1.15.11", "skillctlVersion": "0.1.0",
        "skillctl": {
            "version": "0.1.0", "platforms": ["linux-x86_64", "linux-aarch64"],
            "sha256": "08fab45a1670460a52f974c0203b5cd7c8a1f7deb0854bbb62a1adb7a14b4c82",
            "license": "MIT", "sourceUrl": "https://github.com/tellbom/skillify/archive/refs/tags/v0.1.0.tar.gz",
            "intranetUri": "file:///opt/skillify/offline/skillctl/0.1.0/skillctl-0.1.0-approval-placeholder.json",
            "installable": False,
        }, "artifacts": [{
        "version": "1.15.11", "skillctlVersion": "0.1.0", "os": "linux", "arch": "x86_64",
        "libc": "glibc", "cpu": "avx2", "sha256": "a" * 64, "license": "MIT",
        "sourceUrl": "https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-x64.tar.gz",
        "intranetUri": uri,
    }]}


def test_repository_manifest_matches_schema_and_has_no_latest() -> None:
    data = load_manifest(MANIFEST); validate_manifest(data)
    assert "latest" not in json.dumps(data).lower()
    assert len(data["artifacts"]) == 6


def test_runbook_copies_manifest_and_artifact_to_configured_layout() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "install -m 0644 /media/skillify-opencode/opencode-manifest.json \\" in text
    assert "  /opt/skillify/offline/opencode/opencode-manifest.json" in text
    assert "install -m 0644 /media/skillify-opencode/v1.15.11/opencode-linux-x64-baseline.tar.gz \\" in text
    assert "  /opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64-baseline.tar.gz" in text
    assert "SKILLIFY_OPENCODE_MANIFEST_PATH=/opt/skillify/offline/opencode/opencode-manifest.json" in text


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


@pytest.mark.parametrize("unavailable", ["missing", "directory"])
def test_missing_or_unreadable_artifact_has_stable_domain_error(
    tmp_path: Path, unavailable: str,
) -> None:
    path = tmp_path / "opencode.tar.gz"
    if unavailable == "directory":
        path.mkdir()
    artifact = select_artifact(
        _data(), version="1.15.11", os_name="linux", arch="x86_64",
        libc="glibc", cpu="avx2",
    )

    with pytest.raises(ArtifactNotFound, match="artifact is unavailable"):
        verify_artifact(path, artifact)


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

    failed = [check for check in checks if not check.ok]
    assert len(failed) == 1
    assert failed[0].name == "opencode-version"


@pytest.mark.parametrize(
    ("case", "expected_name", "detail", "hint"),
    [
        ("manifest", "opencode-manifest", "manifest", "approved manifest"),
        ("selector", "opencode-platform", "no exact artifact", "supported platform"),
        ("missing", "opencode-checksum", "artifact is unavailable", "approved artifact"),
        ("corrupt", "opencode-checksum", "checksum mismatch", "approved artifact"),
        ("version-mismatch", "opencode-version", "expected 1.15.11, got 1.15.10", "approved OpenCode"),
        ("version-nonzero", "opencode-version", "version command failed", "approved OpenCode"),
        ("version-timeout", "opencode-version", "version command timed out", "approved OpenCode"),
    ],
)
def test_distribution_diagnostics_identify_the_failed_stage(
    tmp_path: Path, case: str, expected_name: str, detail: str, hint: str,
) -> None:
    from skillify.install.opencode_distribution import check_opencode_distribution

    payload = b"approved opencode bundle"
    data = _data(); data["artifacts"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{" if case == "manifest" else json.dumps(data), encoding="utf-8")
    artifact_root = tmp_path / "artifacts"; artifact_root.mkdir()
    artifact_path = artifact_root / "opencode-linux-x64.tar.gz"
    if case != "missing":
        artifact_path.write_bytes(b"corrupt" if case == "corrupt" else payload)

    def version_runner(argv: list[str]) -> str:
        if case == "version-nonzero":
            raise subprocess.CalledProcessError(2, argv)
        if case == "version-timeout":
            raise subprocess.TimeoutExpired(argv, 5)
        return "1.15.10\n" if case == "version-mismatch" else "1.15.11\n"

    checks = check_opencode_distribution(
        manifest_path=manifest,
        artifact_root=artifact_root,
        platform_detector=(
            (lambda: ("linux", "x86_64", "musl", "avx2"))
            if case == "selector"
            else (lambda: ("linux", "x86_64", "glibc", "avx2"))
        ),
        version_runner=version_runner,
    )

    failed = [check for check in checks if not check.ok]
    assert len(failed) == 1
    assert failed[0].name == expected_name
    assert detail in failed[0].detail
    assert hint in failed[0].hint
