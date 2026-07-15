from __future__ import annotations

import hmac, json, platform, subprocess, sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from skillify.install.extract import sha256_file


class DistributionError(Exception): pass
class ManifestInvalid(DistributionError): pass
class ArtifactNotFound(DistributionError): pass
class ArtifactCorrupt(DistributionError): pass


@dataclass(frozen=True)
class OpenCodeArtifact:
    version: str; skillctl_version: str; os: str; arch: str; libc: str; cpu: str
    sha256: str; license: str; source_url: str; intranet_uri: str


@dataclass(frozen=True)
class DistributionCheck:
    name: str
    ok: bool
    detail: str
    hint: str = ""


_ARTIFACT_REQUIRED = ["version", "skillctlVersion", "os", "arch", "libc", "cpu", "sha256", "license", "sourceUrl", "intranetUri"]
_APPROVED_FILENAMES = {
    ("x86_64", "glibc", "avx2"): "opencode-linux-x64.tar.gz",
    ("x86_64", "glibc", "baseline"): "opencode-linux-x64-baseline.tar.gz",
    ("x86_64", "musl", "avx2"): "opencode-linux-x64-musl.tar.gz",
    ("x86_64", "musl", "baseline"): "opencode-linux-x64-baseline-musl.tar.gz",
    ("aarch64", "glibc", "arm64"): "opencode-linux-arm64.tar.gz",
    ("aarch64", "musl", "arm64"): "opencode-linux-arm64-musl.tar.gz",
}
MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["schemaVersion", "opencodeVersion", "skillctlVersion", "artifacts"],
    "properties": {
        "schemaVersion": {"const": 1}, "opencodeVersion": {"const": "1.15.11"},
        "skillctlVersion": {"const": "0.1.0"},
        "artifacts": {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
            "required": _ARTIFACT_REQUIRED, "properties": {
                "version": {"const": "1.15.11"}, "skillctlVersion": {"const": "0.1.0"},
                "os": {"const": "linux"}, "arch": {"enum": ["x86_64", "aarch64"]},
                "libc": {"enum": ["glibc", "musl"]}, "cpu": {"enum": ["avx2", "baseline", "arm64"]},
                "sha256": {"pattern": "^[0-9a-f]{64}$"}, "license": {"const": "MIT"},
                "sourceUrl": {"type": "string"}, "intranetUri": {"type": "string"},
            }}},
    },
}


def load_manifest(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ManifestInvalid("manifest must be an object")
    return value


def validate_manifest(data: Mapping[str, object]) -> None:
    errors = sorted(Draft202012Validator(MANIFEST_SCHEMA).iter_errors(data), key=lambda error: list(error.path))
    if errors: raise ManifestInvalid(errors[0].message)
    if "latest" in json.dumps(data).lower(): raise ManifestInvalid("floating latest is forbidden")
    seen = set()
    for item in data["artifacts"]:
        selector = (item["arch"], item["libc"], item["cpu"])
        filename = _APPROVED_FILENAMES.get(selector)
        expected_source = f"https://github.com/anomalyco/opencode/releases/download/v1.15.11/{filename}"
        expected_runtime = f"file:///opt/skillify/offline/opencode/v1.15.11/{filename}"
        if filename is None or item["sourceUrl"] != expected_source:
            raise ManifestInvalid("sourceUrl must be the pinned official GitHub release")
        if item["intranetUri"] != expected_runtime:
            raise ManifestInvalid("intranetUri must be an absolute local file: bundle URI")
        key = tuple(item[name] for name in ("version", "os", "arch", "libc", "cpu"))
        if key in seen: raise ManifestInvalid("duplicate artifact selector")
        seen.add(key)


def select_artifact(
    data: Mapping[str, object],
    *,
    version: str,
    os_name: str,
    arch: str,
    libc: str,
    cpu: str,
) -> OpenCodeArtifact:
    validate_manifest(data)
    matches = [item for item in data["artifacts"] if (item["version"], item["os"], item["arch"], item["libc"], item["cpu"]) == (version, os_name, arch, libc, cpu)]
    if len(matches) != 1: raise ManifestInvalid("no exact artifact for version and platform")
    item = matches[0]
    return OpenCodeArtifact(item["version"], item["skillctlVersion"], item["os"], item["arch"], item["libc"], item["cpu"], item["sha256"], item["license"], item["sourceUrl"], item["intranetUri"])


def verify_artifact(path: Path, artifact: OpenCodeArtifact) -> None:
    try:
        actual = sha256_file(path)
    except OSError as exc:
        raise ArtifactNotFound(f"{path}: OpenCode artifact is unavailable") from exc
    if not hmac.compare_digest(actual, artifact.sha256):
        raise ArtifactCorrupt(f"{path}: OpenCode artifact checksum mismatch")


def detect_opencode_platform() -> tuple[str, str, str, str]:
    if sys.platform != "linux": raise ValueError("OpenCode S1 supports Linux only")
    machine = platform.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine)
    if arch is None: raise ValueError(f"unsupported architecture: {machine}")
    libc_name = platform.libc_ver()[0].lower()
    libc = "musl" if "musl" in libc_name else "glibc" if "glibc" in libc_name else ""
    if not libc: raise ValueError("unable to detect glibc or musl")
    if arch == "aarch64": return "linux", arch, libc, "arm64"
    flags = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").lower()
    return "linux", arch, libc, "avx2" if " avx2" in flags else "baseline"


def opencode_version(argv: list[str]) -> str:
    completed = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=5)
    return completed.stdout


def resolve_distribution_paths(
    manifest: str | None,
    artifacts: str | None,
) -> tuple[Path, Path] | None:
    if manifest is None and artifacts is None: return None
    if not manifest or not artifacts:
        raise ValueError("opencode_manifest_path and opencode_artifact_root must be configured together")
    manifest_path, artifact_root = Path(manifest), Path(artifacts)
    if not manifest_path.is_absolute() or not artifact_root.is_absolute():
        raise ValueError("OpenCode distribution paths must be absolute")
    return manifest_path.resolve(), artifact_root.resolve()


def check_opencode_distribution(
    *,
    manifest_path: Path,
    artifact_root: Path,
    platform_detector: Callable[[], tuple[str, str, str, str]],
    version_runner: Callable[[list[str]], str],
) -> list[DistributionCheck]:
    try:
        data = load_manifest(manifest_path)
        validate_manifest(data)
    except (OSError, DistributionError, ValueError) as exc:
        return [DistributionCheck(
            "opencode-manifest", False, f"manifest unavailable or invalid: {exc}",
            "install the approved manifest and configure its absolute path",
        )]
    manifest_check = DistributionCheck("opencode-manifest", True, str(manifest_path))

    try:
        os_name, arch, libc, cpu = platform_detector()
        artifact = select_artifact(
            data, version="1.15.11", os_name=os_name, arch=arch, libc=libc, cpu=cpu,
        )
    except (DistributionError, OSError, ValueError) as exc:
        return [manifest_check, DistributionCheck(
            "opencode-platform", False, str(exc),
            "select an approved artifact for a supported platform",
        )]
    platform_check = DistributionCheck(
        "opencode-platform", True, f"{os_name}/{arch}/{libc}/{cpu}",
    )

    local_path = artifact_root / Path(urlsplit(artifact.intranet_uri).path).name
    try:
        verify_artifact(local_path, artifact)
    except (ArtifactNotFound, ArtifactCorrupt) as exc:
        return [manifest_check, platform_check, DistributionCheck(
            "opencode-checksum", False, str(exc),
            "stage the approved artifact and verify its SHA-256 checksum",
        )]
    checksum_check = DistributionCheck("opencode-checksum", True, artifact.sha256)

    try:
        actual = version_runner(["opencode", "--version"])
    except subprocess.TimeoutExpired as exc:
        return [manifest_check, platform_check, DistributionCheck(
            "opencode-version", False, f"version command timed out: {exc}",
            "activate the approved OpenCode v1.15.11 binary",
        ), checksum_check]
    except (subprocess.SubprocessError, OSError) as exc:
        return [manifest_check, platform_check, DistributionCheck(
            "opencode-version", False, f"version command failed: {exc}",
            "activate the approved OpenCode v1.15.11 binary",
        ), checksum_check]
    if actual.strip() != artifact.version:
        return [manifest_check, platform_check, DistributionCheck(
            "opencode-version", False,
            f"expected {artifact.version}, got {actual.strip()}",
            "activate the approved OpenCode v1.15.11 binary",
        ), checksum_check]
    return [
        manifest_check,
        platform_check,
        DistributionCheck("opencode-version", True, artifact.version),
        checksum_check,
    ]
