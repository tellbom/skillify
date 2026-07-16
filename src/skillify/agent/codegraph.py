"""Thin lifecycle integration for the pinned external CodeGraph binary."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skillify.install.extract import safe_extract


SUPPORTED_CODEGRAPH_VERSION = "0.9.6"


class CodeGraphError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodeGraphArtifact:
    version: str
    os: str
    arch: str
    filename: str
    sha256: str
    license: str
    source_url: str
    intranet_uri: str


@dataclass(frozen=True)
class CodeGraphStatus:
    available: bool
    detail: str
    use_native_search: bool


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodeGraphError("CodeGraph manifest is unavailable or invalid") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise CodeGraphError("CodeGraph manifest schemaVersion must be 1")
    if value.get("codegraphVersion") != SUPPORTED_CODEGRAPH_VERSION:
        raise CodeGraphError("CodeGraph manifest version is unsupported")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise CodeGraphError("CodeGraph manifest requires artifacts")
    for item in artifacts:
        if not isinstance(item, dict):
            raise CodeGraphError("CodeGraph artifact must be an object")
        required = {"version", "os", "arch", "filename", "sha256", "license", "sourceUrl", "intranetUri"}
        if set(item) != required or item["version"] != SUPPORTED_CODEGRAPH_VERSION:
            raise CodeGraphError("CodeGraph artifact metadata is invalid")
        if item["license"] != "MIT" or not isinstance(item["sha256"], str) or len(item["sha256"]) != 64:
            raise CodeGraphError("CodeGraph artifact approval metadata is invalid")
    return value


def select_artifact(manifest: dict[str, Any], *, os_name: str, arch: str) -> CodeGraphArtifact:
    load_version = manifest.get("codegraphVersion")
    if load_version != SUPPORTED_CODEGRAPH_VERSION:
        raise CodeGraphError("CodeGraph manifest version is unsupported")
    matches = [item for item in manifest.get("artifacts", []) if item.get("os") == os_name and item.get("arch") == arch]
    if len(matches) != 1:
        raise CodeGraphError("no CodeGraph artifact for this platform")
    item = matches[0]
    return CodeGraphArtifact(
        item["version"], item["os"], item["arch"], item["filename"], item["sha256"],
        item["license"], item["sourceUrl"], item["intranetUri"],
    )


def current_platform() -> tuple[str, str]:
    os_name = {"linux": "linux", "darwin": "darwin"}.get(platform.system().lower())
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    if os_name is None or arch is None:
        raise CodeGraphError("CodeGraph platform is unsupported")
    return os_name, arch


def verify_artifact(path: Path, artifact: CodeGraphArtifact) -> None:
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise CodeGraphError("CodeGraph artifact is unavailable") from exc
    if digest != artifact.sha256:
        raise CodeGraphError("CodeGraph artifact checksum mismatch")


def install_artifact(archive: Path, artifact: CodeGraphArtifact, install_root: Path) -> Path:
    verify_artifact(archive, artifact)
    destination = Path(install_root) / artifact.version
    if not destination.exists():
        safe_extract(archive, destination)
    candidates = [path for path in destination.rglob("codegraph") if path.is_file()]
    if not candidates:
        raise CodeGraphError("CodeGraph binary is missing from the approved artifact")
    binary = candidates[0]
    binary.chmod(binary.stat().st_mode | 0o100)
    return binary


def codegraph_version(executable: str | Path = "codegraph") -> str:
    try:
        completed = subprocess.run(
            [str(executable), "--version"], check=True, capture_output=True, text=True, timeout=5,
            env={key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CodeGraphError("CodeGraph executable is unavailable") from exc
    value = completed.stdout.strip().removeprefix("v")
    if value != SUPPORTED_CODEGRAPH_VERSION:
        raise CodeGraphError("CodeGraph executable version is unsupported")
    return value


def update_index(workspace: Path, *, executable: str | Path = "codegraph") -> None:
    root = Path(workspace).resolve(strict=True)
    command = "sync" if (root / ".codegraph").is_dir() else "init"
    argv = [str(executable), command, str(root)]
    if command == "init":
        argv.append("--index")
    env = {**os.environ, "CODEGRAPH_NO_DOWNLOAD": "1", "CODEGRAPH_TELEMETRY": "0"}
    try:
        subprocess.run(argv, check=True, timeout=120, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CodeGraphError("CodeGraph index update failed; continue with native grep/read") from exc


def index_status(workspace: Path, *, executable: str | Path = "codegraph") -> CodeGraphStatus:
    if shutil.which(str(executable)) is None and not Path(executable).is_file():
        return CodeGraphStatus(False, "CodeGraph executable is unavailable", True)
    try:
        codegraph_version(executable)
    except CodeGraphError as exc:
        return CodeGraphStatus(False, str(exc), True)
    if not (Path(workspace) / ".codegraph").is_dir():
        return CodeGraphStatus(False, "CodeGraph index is not initialized", True)
    return CodeGraphStatus(True, "CodeGraph index is ready", False)


def mcp_environment(workspace: Path) -> dict[str, str]:
    return {
        "CODEGRAPH_NO_DOWNLOAD": "1",
        "CODEGRAPH_TELEMETRY": "0",
        "CODEGRAPH_PROJECT_ROOT": str(Path(workspace).absolute()),
    }
