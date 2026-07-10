"""Tests for T1.4/C2 — precise Forgejo release-asset resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillify.install.resolver import ResolveError, resolve_release_artifact
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
