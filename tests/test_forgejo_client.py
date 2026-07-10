"""Tests for T1.3's ForgejoClient against the fake in-process Forgejo API."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillify.publish.forgejo_client import ForgejoClient, ForgejoError
from tests.fake_forgejo import fake_forgejo  # noqa: F401 (fixture import)


def test_ensure_org_repo_creates_when_missing(fake_forgejo) -> None:
    client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")
    assert client.repo_exists("excel", "pivot-analysis") is False
    client.ensure_org_repo("excel", "pivot-analysis")
    assert client.repo_exists("excel", "pivot-analysis") is True
    # Idempotent — calling again on an existing repo must not error.
    client.ensure_org_repo("excel", "pivot-analysis")


def test_create_release_and_upload_assets(fake_forgejo, tmp_path: Path) -> None:
    client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")
    client.ensure_org_repo("excel", "pivot-analysis")

    assert client.get_release_by_tag("excel", "pivot-analysis", "v0.1.0") is None
    release = client.create_release(
        "excel", "pivot-analysis", tag_name="v0.1.0", name="pivot-analysis 0.1.0", body="notes"
    )
    assert release.tag_name == "v0.1.0"

    asset_file = tmp_path / "pivot-analysis-0.1.0.tar.gz"
    asset_file.write_bytes(b"fake tarball bytes")
    asset = client.upload_release_asset("excel", "pivot-analysis", release.id, asset_file)
    assert asset.name == "pivot-analysis-0.1.0.tar.gz"

    fetched = client.get_release_by_tag("excel", "pivot-analysis", "v0.1.0")
    assert fetched is not None
    assert [a.name for a in fetched.assets] == ["pivot-analysis-0.1.0.tar.gz"]


def test_get_latest_release_and_download(fake_forgejo, tmp_path: Path) -> None:
    client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")
    client.ensure_org_repo("excel", "pivot-analysis")
    assert client.get_latest_release("excel", "pivot-analysis") is None

    release = client.create_release("excel", "pivot-analysis", tag_name="v0.1.0", name="v0.1.0")
    asset_file = tmp_path / "payload.tar.gz"
    asset_file.write_bytes(b"payload-bytes-for-download-test")
    asset = client.upload_release_asset("excel", "pivot-analysis", release.id, asset_file)

    latest = client.get_latest_release("excel", "pivot-analysis")
    assert latest is not None
    assert latest.tag_name == "v0.1.0"

    dest = tmp_path / "downloaded.tar.gz"
    client.download(asset.browser_download_url, dest)
    assert dest.read_bytes() == b"payload-bytes-for-download-test"


def test_bad_token_raises_on_repo_check(fake_forgejo) -> None:
    fake_forgejo.state.required_token = "correct-token"
    client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "wrong-token")
    with pytest.raises(ForgejoError):
        client.repo_exists("excel", "pivot-analysis")


def test_unreachable_host_raises_forgejo_error() -> None:
    client = ForgejoClient("http://127.0.0.1:1", "tok")
    with pytest.raises(ForgejoError):
        client.repo_exists("excel", "pivot-analysis")


def test_get_raw_file_present_and_missing(fake_forgejo) -> None:
    fake_forgejo.state.raw_files["excel/pivot-analysis/v0.1.0/README.md"] = "# Pivot Analysis\n"
    client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")

    content = client.get_raw_file("excel", "pivot-analysis", "README.md", "v0.1.0")
    assert content == "# Pivot Analysis\n"

    missing = client.get_raw_file("excel", "pivot-analysis", "MISSING.md", "v0.1.0")
    assert missing is None
