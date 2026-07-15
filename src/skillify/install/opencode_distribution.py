from __future__ import annotations

import hmac, json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

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
    if not hmac.compare_digest(sha256_file(path), artifact.sha256):
        raise ArtifactCorrupt(f"{path}: OpenCode artifact checksum mismatch")
