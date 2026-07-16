from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from skillify.agent.codegraph import (
    CodeGraphArtifact,
    CodeGraphError,
    SUPPORTED_CODEGRAPH_VERSION,
    codegraph_version,
    load_manifest,
    select_artifact,
    verify_artifact,
)


ROOT = Path(__file__).resolve().parents[1]


def test_pinned_manifest_selects_linux_artifact() -> None:
    value = load_manifest(ROOT / "infra/offline/codegraph-manifest.json")
    artifact = select_artifact(value, os_name="linux", arch="x64")
    assert artifact.version == SUPPORTED_CODEGRAPH_VERSION
    assert artifact.filename == "codegraph-linux-x64.tar.gz"


def test_artifact_checksum_accepts_exact_content_and_rejects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "codegraph.tar.gz"
    path.write_bytes(b"approved")
    artifact = CodeGraphArtifact(
        SUPPORTED_CODEGRAPH_VERSION, "linux", "x64", path.name,
        hashlib.sha256(b"approved").hexdigest(), "MIT", "https://example.invalid", "file:///approved",
    )
    verify_artifact(path, artifact)
    path.write_bytes(b"tampered")
    with pytest.raises(CodeGraphError, match="checksum"):
        verify_artifact(path, artifact)


def test_version_parser_requires_the_pinned_version(tmp_path: Path) -> None:
    executable = tmp_path / "codegraph"
    executable.write_text(f"#!/bin/sh\nprintf '{SUPPORTED_CODEGRAPH_VERSION}\\n'\n")
    executable.chmod(0o755)
    assert codegraph_version(executable) == SUPPORTED_CODEGRAPH_VERSION
    executable.write_text("#!/bin/sh\nprintf '0.0.1\\n'\n")
    executable.chmod(0o755)
    with pytest.raises(CodeGraphError, match="unsupported"):
        codegraph_version(executable)
