"""Validation for the approved Shogun artifact; installation remains an offline operation."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


SHOGUN_VERSION = "v5.2.0"
SHOGUN_COMMIT = "431b86a6907dd9ce2a0e9789f1e917ba71d1d184"
SUPPORTED_PLATFORM = "linux-x86_64"
REQUIRED_HOST_DEPENDENCIES = ("tmux", "flock", "inotifywait", "python3", "od")
CLI_EXECUTABLES = {"opencode": "opencode", "claude-code": "claude"}


class ShogunDistributionError(RuntimeError):
    pass


@dataclass(frozen=True)
class DependencyStatus:
    available: bool
    missing: tuple[str, ...]
    detail: str


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShogunDistributionError("Shogun manifest is unavailable or invalid") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ShogunDistributionError("Shogun manifest schemaVersion must be 1")
    expected = {
        "name": "multi-agent-shogun", "version": SHOGUN_VERSION,
        "commit": SHOGUN_COMMIT, "license": "MIT", "platform": SUPPORTED_PLATFORM,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ShogunDistributionError("Shogun approval metadata is unsupported")
    if type(value.get("installable")) is not bool:
        raise ShogunDistributionError("Shogun installable approval flag is invalid")
    artifact = value.get("artifact")
    if not isinstance(artifact, dict) or set(artifact) != {
        "filename", "sha256", "sourceUrl", "intranetUri",
    }:
        raise ShogunDistributionError("Shogun artifact metadata is invalid")
    digest = artifact.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ShogunDistributionError("Shogun artifact checksum is invalid")
    if value.get("forbiddenEntrypoints") != ["first_setup.sh"]:
        raise ShogunDistributionError("Shogun online setup must remain forbidden")
    if value.get("allowedClis") != ["opencode", "claude"]:
        raise ShogunDistributionError("Shogun CLI scope must remain OpenCode and Claude only")
    requirements = value.get("bundleRequirements")
    if not isinstance(requirements, list) or not {
        ".venv/bin/python", "config/settings.yaml", "shutsujin_departure.sh",
    }.issubset(requirements):
        raise ShogunDistributionError("Shogun offline bundle requirements are incomplete")
    return value


def require_installable(manifest: dict[str, Any]) -> None:
    if manifest.get("installable") is not True:
        raise ShogunDistributionError(
            "Shogun offline bundle is not approved; single/delegated remain available"
        )


def verify_artifact(path: Path, manifest: dict[str, Any]) -> None:
    expected = manifest["artifact"]["sha256"]
    try:
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise ShogunDistributionError("Shogun artifact is unavailable") from exc
    if actual != expected:
        raise ShogunDistributionError("Shogun artifact checksum mismatch")


def check_bundle_layout(root: Path, manifest: dict[str, Any]) -> None:
    base = Path(root)
    missing = [name for name in manifest["bundleRequirements"] if not (base / name).exists()]
    if missing:
        raise ShogunDistributionError("Shogun offline bundle is incomplete: " + ", ".join(missing))


def check_host_dependencies(
    preferred_cli: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> DependencyStatus:
    executable = CLI_EXECUTABLES.get(preferred_cli)
    if executable is None:
        raise ValueError("Shogun supports only opencode or claude-code")
    required = (*REQUIRED_HOST_DEPENDENCIES, executable)
    missing = tuple(name for name in required if which(name) is None)
    return DependencyStatus(
        not missing, missing,
        "ready" if not missing else "missing host dependencies: " + ", ".join(missing),
    )
