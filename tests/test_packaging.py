"""Tests for T1.2 — packaging (tarball + checksum + artifact manifest)."""

from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path

import pytest

from skillify.mcp.registry import load_mcp_artifact
from skillify.packaging.pack import PackagingError, pack_mcp, pack_skill, sha256_file
from tests.fixtures import VALID_MANIFEST, VALID_SKILL_MD


def _make_skill(tmp_path: Path, name: str = "pivot-analysis", namespace: str = "excel") -> Path:
    namespace_dir = tmp_path / namespace
    namespace_dir.mkdir(parents=True, exist_ok=True)
    skill_dir = namespace_dir / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")
    (skill_dir / "skill.yaml").write_text(VALID_MANIFEST, encoding="utf-8")
    (skill_dir / "README.md").write_text("hello\n", encoding="utf-8")
    (skill_dir / "resources").mkdir()
    (skill_dir / "resources" / "data.txt").write_bytes(b"some data\n")
    return skill_dir


def test_pack_skill_produces_expected_artifacts(tmp_path: Path) -> None:
    skill_dir = _make_skill(tmp_path)
    out = tmp_path / "dist"
    result = pack_skill(skill_dir, out)

    assert result.tarball_path.is_file()
    assert result.checksum_path.is_file()
    assert result.artifact_manifest_path.is_file()
    assert result.namespace == "excel"
    assert result.name == "pivot-analysis"
    assert result.version == "0.1.0"
    assert result.sha256 == sha256_file(result.tarball_path)
    assert result.checksum_path.read_text(encoding="utf-8").startswith(result.sha256)


def test_pack_skill_is_reproducible(tmp_path: Path) -> None:
    skill_dir = _make_skill(tmp_path)

    out1 = tmp_path / "dist1"
    result1 = pack_skill(skill_dir, out1)
    time.sleep(1.1)  # cross a whole second so a non-zeroed mtime would produce a different digest
    out2 = tmp_path / "dist2"
    result2 = pack_skill(skill_dir, out2)

    assert result1.sha256 == result2.sha256
    assert result1.tarball_path.read_bytes() == result2.tarball_path.read_bytes()


def test_pack_skill_rejects_invalid_skill(tmp_path: Path) -> None:
    skill_dir = _make_skill(tmp_path)
    (skill_dir / "SKILL.md").unlink()

    with pytest.raises(PackagingError):
        pack_skill(skill_dir, tmp_path / "dist")


def test_tarball_round_trips_file_contents(tmp_path: Path) -> None:
    skill_dir = _make_skill(tmp_path)
    result = pack_skill(skill_dir, tmp_path / "dist")

    with tarfile.open(result.tarball_path, "r:gz") as tar:
        names = sorted(m.name for m in tar.getmembers())
        assert names == ["README.md", "resources/data.txt", "SKILL.md", "skill.yaml"] or names == sorted(
            ["README.md", "resources/data.txt", "SKILL.md", "skill.yaml"]
        )
        extracted = tar.extractfile("resources/data.txt")
        assert extracted is not None
        assert extracted.read() == b"some data\n"


def test_excluded_dirs_are_not_packaged(tmp_path: Path) -> None:
    skill_dir = _make_skill(tmp_path)
    (skill_dir / "__pycache__").mkdir()
    (skill_dir / "__pycache__" / "junk.pyc").write_bytes(b"\x00")
    (skill_dir / ".git").mkdir()
    (skill_dir / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    result = pack_skill(skill_dir, tmp_path / "dist")
    with tarfile.open(result.tarball_path, "r:gz") as tar:
        names = [m.name for m in tar.getmembers()]
    assert not any("__pycache__" in n or ".git" in n for n in names)


def test_artifact_manifest_embeds_skill_manifest(tmp_path: Path) -> None:
    skill_dir = _make_skill(tmp_path)
    result = pack_skill(skill_dir, tmp_path / "dist")

    import json

    data = json.loads(result.artifact_manifest_path.read_text(encoding="utf-8"))
    assert data["sha256"] == result.sha256
    assert data["skillManifest"]["name"] == "pivot-analysis"
    assert data["artifactKind"] == "skill"


def _mcp_metadata(checksum: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "artifactKind": "mcp",
        "namespace": "approved",
        "name": "echo",
        "version": "1.2.3",
        "forgejoRelease": "v1.2.3",
        "commit": "b" * 40,
        "checksum": checksum,
        "license": "MIT",
        "source": "https://forgejo.internal/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz",
        "transport": "stdio",
        "command": ["/opt/skillify/mcp/echo/bin/server"],
        "environment": ["PATH"],
        "permissions": {
            "readPaths": [], "writePaths": [], "commands": {}, "networkDomains": [],
            "mcpServers": [], "databaseResources": [], "unattended": False, "confirm": [],
        },
        "enabled": True,
    }


def test_pack_mcp_preserves_prebuilt_archive_and_writes_governed_sidecar(tmp_path: Path) -> None:
    archive = tmp_path / "approved.tar.gz"
    archive.write_bytes(b"immutable approved MCP archive")
    artifact = load_mcp_artifact(_mcp_metadata(sha256_file(archive)))

    result = pack_mcp(artifact, archive, tmp_path / "dist")

    assert result.tarball_path.read_bytes() == archive.read_bytes()
    data = __import__("json").loads(result.artifact_manifest_path.read_text(encoding="utf-8"))
    assert data["artifactKind"] == "mcp"
    assert data["sha256"] == result.sha256
    assert data["mcpArtifact"]["command"] == ["/opt/skillify/mcp/echo/bin/server"]
    assert "secret" not in result.artifact_manifest_path.read_text(encoding="utf-8")


def test_pack_mcp_rejects_archive_that_does_not_match_metadata(tmp_path: Path) -> None:
    archive = tmp_path / "approved.tar.gz"
    archive.write_bytes(b"tampered")
    artifact = load_mcp_artifact(_mcp_metadata("a" * 64))

    with pytest.raises(ValueError, match="checksum"):
        pack_mcp(artifact, archive, tmp_path / "dist")
