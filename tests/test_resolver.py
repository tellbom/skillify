"""Tests for T1.4/C2 — precise Forgejo release-asset resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillify.install.resolver import (
    CapabilityIntegrityError,
    CapabilityResolveError,
    Coordinate,
    ReleaseRecord,
    ResolveError,
    resolve_capability_graph,
    resolve_release_artifact,
    verify_locked_artifact,
)
from skillify.publish.forgejo_client import ForgejoClient
from tests.fake_forgejo import fake_forgejo  # noqa: F401


def _client(fake_forgejo) -> ForgejoClient:
    return ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")


def test_resolver_picks_exact_basename_among_multiple_assets(tmp_path: Path, fake_forgejo) -> None:
    client = _client(fake_forgejo)
    client.ensure_org_repo("excel", "pivot-analysis")
    release = client.create_release("excel", "pivot-analysis", tag_name="v0.1.0", name="v0.1.0")

    # A decoy asset with an unrelated name must not be picked.
    decoy = tmp_path / "decoy.tar.gz"
    decoy.write_bytes(b"decoy bytes")
    client.upload_release_asset("excel", "pivot-analysis", release.id, decoy)

    real = tmp_path / "excel-pivot-analysis-0.1.0.tar.gz"
    real.write_bytes(b"real tarball bytes")
    client.upload_release_asset("excel", "pivot-analysis", release.id, real)

    checksum = tmp_path / "excel-pivot-analysis-0.1.0.sha256"
    checksum.write_text("deadbeef  excel-pivot-analysis-0.1.0.tar.gz\n", encoding="utf-8")
    client.upload_release_asset("excel", "pivot-analysis", release.id, checksum)

    artifact = resolve_release_artifact(client, "excel", "excel", "pivot-analysis", "0.1.0")
    downloaded = tmp_path / "out.tar.gz"
    client.download(artifact.tarball_url, downloaded)
    assert downloaded.read_bytes() == b"real tarball bytes"


def test_resolver_raises_when_no_matching_basename(tmp_path: Path, fake_forgejo) -> None:
    client = _client(fake_forgejo)
    client.ensure_org_repo("excel", "pivot-analysis")
    release = client.create_release("excel", "pivot-analysis", tag_name="v0.1.0", name="v0.1.0")

    wrong = tmp_path / "totally-different-name.tar.gz"
    wrong.write_bytes(b"x")
    client.upload_release_asset("excel", "pivot-analysis", release.id, wrong)

    with pytest.raises(ResolveError, match="no asset named"):
        resolve_release_artifact(client, "excel", "excel", "pivot-analysis", "0.1.0")


def test_resolver_cross_checks_artifact_manifest_identity(tmp_path: Path, fake_forgejo) -> None:
    client = _client(fake_forgejo)
    client.ensure_org_repo("excel", "pivot-analysis")
    release = client.create_release("excel", "pivot-analysis", tag_name="v0.1.0", name="v0.1.0")

    tarball = tmp_path / "excel-pivot-analysis-0.1.0.tar.gz"
    tarball.write_bytes(b"real tarball bytes")
    client.upload_release_asset("excel", "pivot-analysis", release.id, tarball)

    # artifact.json claims a different name than the basename it's attached to.
    bad_manifest = tmp_path / "excel-pivot-analysis-0.1.0.artifact.json"
    bad_manifest.write_text(
        json.dumps({"namespace": "excel", "name": "something-else", "version": "0.1.0"}), encoding="utf-8"
    )
    client.upload_release_asset("excel", "pivot-analysis", release.id, bad_manifest)

    with pytest.raises(ResolveError, match="identity mismatch"):
        resolve_release_artifact(client, "excel", "excel", "pivot-analysis", "0.1.0")


def test_resolver_accepts_consistent_artifact_manifest(tmp_path: Path, fake_forgejo) -> None:
    client = _client(fake_forgejo)
    client.ensure_org_repo("excel", "pivot-analysis")
    release = client.create_release("excel", "pivot-analysis", tag_name="v0.1.0", name="v0.1.0")

    tarball = tmp_path / "excel-pivot-analysis-0.1.0.tar.gz"
    tarball.write_bytes(b"real tarball bytes")
    client.upload_release_asset("excel", "pivot-analysis", release.id, tarball)

    good_manifest = tmp_path / "excel-pivot-analysis-0.1.0.artifact.json"
    good_manifest.write_text(
        json.dumps({"namespace": "excel", "name": "pivot-analysis", "version": "0.1.0"}), encoding="utf-8"
    )
    client.upload_release_asset("excel", "pivot-analysis", release.id, good_manifest)

    artifact = resolve_release_artifact(client, "excel", "excel", "pivot-analysis", "0.1.0")
    assert artifact.version == "0.1.0"


class FakeReleaseCatalog:
    def __init__(self, records: tuple[ReleaseRecord, ...]) -> None:
        self._records = {record.coordinate: record for record in records}
        self.calls: list[Coordinate] = []

    def get(self, coordinate: Coordinate) -> ReleaseRecord | None:
        self.calls.append(coordinate)
        return self._records.get(coordinate)


def _release(
    kind: str,
    identifier: str,
    version: str,
    *dependencies: Coordinate,
    checksum: str = "a" * 64,
) -> ReleaseRecord:
    return ReleaseRecord(
        coordinate=Coordinate(kind, identifier, version),
        forgejo_release=f"v{version}",
        commit="1" * 40,
        checksum=checksum,
        dependencies=dependencies,
    )


def test_capability_graph_is_dependency_first_and_peer_deterministic() -> None:
    root = _release(
        "workflow",
        "dev/feature",
        "1.0.0",
        Coordinate("skill", "ns/zeta", "1.0.0"),
        Coordinate("skill", "ns/alpha", "1.0.0"),
    )
    alpha = _release("skill", "ns/alpha", "1.0.0", Coordinate("mcp", "tools/shared", "2.0.0"))
    zeta = _release("skill", "ns/zeta", "1.0.0", Coordinate("mcp", "tools/shared", "2.0.0"))
    shared = _release("mcp", "tools/shared", "2.0.0")
    catalog = FakeReleaseCatalog((root, zeta, shared, alpha))

    resolved = resolve_capability_graph(root.coordinate, catalog)

    assert [record.coordinate.identifier for record in resolved] == [
        "tools/shared", "ns/alpha", "ns/zeta", "dev/feature",
    ]
    assert catalog.calls.count(shared.coordinate) == 1


def test_resolver_rejects_conflicting_dependency_versions_deterministically() -> None:
    root = _release(
        "workflow", "dev/feature", "1.0.0",
        Coordinate("skill", "ns/a", "1.0.0"),
        Coordinate("skill", "ns/b", "1.0.0"),
    )
    a = _release("skill", "ns/a", "1.0.0", Coordinate("mcp", "tools/shared", "1.0.0"))
    b = _release("skill", "ns/b", "1.0.0", Coordinate("mcp", "tools/shared", "2.0.0"))
    shared1 = _release("mcp", "tools/shared", "1.0.0")
    shared2 = _release("mcp", "tools/shared", "2.0.0")

    with pytest.raises(
        CapabilityResolveError,
        match=r"version conflict for mcp:tools/shared: 1\.0\.0 != 2\.0\.0",
    ):
        resolve_capability_graph(root.coordinate, FakeReleaseCatalog((root, b, shared2, a, shared1)))


def test_resolver_rejects_cycle_with_ordered_path() -> None:
    a = _release("skill", "ns/a", "1.0.0", Coordinate("skill", "ns/b", "1.0.0"))
    b = _release("skill", "ns/b", "1.0.0", Coordinate("skill", "ns/a", "1.0.0"))

    with pytest.raises(
        CapabilityResolveError,
        match=r"cycle: skill:ns/a@1\.0\.0 -> skill:ns/b@1\.0\.0 -> skill:ns/a@1\.0\.0",
    ):
        resolve_capability_graph(a.coordinate, FakeReleaseCatalog((b, a)))


def test_resolver_rejects_missing_release() -> None:
    coordinate = Coordinate("mcp", "tools/echo", "1.0.0")
    with pytest.raises(CapabilityResolveError, match="missing immutable release: mcp:tools/echo@1.0.0"):
        resolve_capability_graph(coordinate, FakeReleaseCatalog(()))


@pytest.mark.parametrize("version", ["latest", "^1.0.0", "1.0", "1.0.0-01"])
def test_coordinate_rejects_non_exact_versions(version: str) -> None:
    with pytest.raises(CapabilityResolveError, match="exact semantic version"):
        Coordinate("skill", "ns/a", version)


def test_release_record_rejects_mutable_or_mismatched_identity() -> None:
    coordinate = Coordinate("skill", "ns/a", "1.0.0")
    with pytest.raises(CapabilityResolveError, match="immutable Forgejo release"):
        ReleaseRecord(coordinate, "latest", "1" * 40, "a" * 64, ())
    with pytest.raises(CapabilityResolveError, match="40-hex"):
        ReleaseRecord(coordinate, "v1.0.0", "bad", "a" * 64, ())


def test_verify_locked_artifact_rejects_tampering(tmp_path: Path) -> None:
    artifact = tmp_path / "bundle.tar.gz"
    artifact.write_bytes(b"tampered")
    with pytest.raises(CapabilityIntegrityError, match="checksum"):
        verify_locked_artifact(artifact, "a" * 64)


def test_verify_locked_artifact_returns_verified_checksum(tmp_path: Path) -> None:
    artifact = tmp_path / "bundle.tar.gz"
    artifact.write_bytes(b"trusted")
    checksum = __import__("hashlib").sha256(b"trusted").hexdigest()
    assert verify_locked_artifact(artifact, checksum) == checksum
