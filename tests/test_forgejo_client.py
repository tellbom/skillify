"""Tests for T1.3's ForgejoClient against the fake in-process Forgejo API."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillify.publish.forgejo_client import ForgejoClient, ForgejoError
from skillify.common.config import SkillifyConfig
from skillify.mcp.registry import load_mcp_artifact
from skillify.packaging.pack import pack_mcp, sha256_file
from skillify.publish.publisher import AlreadyPublishedError, publish_mcp_artifact
from skillify.mcp.registry import McpRegistryError
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


def test_release_body_round_trips(fake_forgejo) -> None:
    """C-1: Release.body is used for version-timeline release notes."""
    client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")
    client.ensure_org_repo("excel", "pivot-analysis")

    release = client.create_release(
        "excel", "pivot-analysis", tag_name="v0.1.0", name="v0.1.0", body="fixed a bug"
    )
    assert release.body == "fixed a bug"

    fetched = client.get_release_by_tag("excel", "pivot-analysis", "v0.1.0")
    assert fetched.body == "fixed a bug"

    default_body = client.create_release("excel", "pivot-analysis", tag_name="v0.2.0", name="v0.2.0")
    assert default_body.body == ""


def test_list_tree_returns_entries_and_empty_on_missing_ref(fake_forgejo) -> None:
    """C-1: list_tree backs the version diff endpoint — 404 (unknown ref) is not an error,
    it's just an empty tree, since the caller decides what a missing version means."""
    client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")

    assert client.list_tree("excel", "pivot-analysis", "v0.1.0") == []

    fake_forgejo.state.trees["excel/pivot-analysis/v0.1.0"] = [
        {"path": "SKILL.md", "sha": "abc123", "type": "blob"},
        {"path": "skill.yaml", "sha": "def456", "type": "blob"},
    ]
    tree = client.list_tree("excel", "pivot-analysis", "v0.1.0")
    assert {e["path"] for e in tree} == {"SKILL.md", "skill.yaml"}


def test_publish_mcp_uses_same_immutable_release_asset_flow(fake_forgejo, tmp_path: Path) -> None:
    archive = tmp_path / "mcp.tar.gz"
    archive.write_bytes(b"approved mcp")
    forgejo_base = f"http://127.0.0.1:{fake_forgejo.server_port}"
    metadata = {
        "schemaVersion": 1, "artifactKind": "mcp", "namespace": "approved", "name": "echo",
        "version": "1.2.3", "forgejoRelease": "v1.2.3", "commit": "b" * 40,
        "checksum": sha256_file(archive), "license": "MIT",
        "source": f"{forgejo_base}/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz",
        "transport": "stdio", "command": ["/opt/skillify/mcp/echo/bin/server"],
        "environment": [], "permissions": {
            "readPaths": [], "writePaths": [], "commands": {}, "networkDomains": [],
            "mcpServers": [], "databaseResources": [], "unattended": False, "confirm": [],
        }, "enabled": True,
    }
    artifact = load_mcp_artifact(metadata, approved_forgejo_base=forgejo_base)
    cfg = SkillifyConfig(
        home=tmp_path / "home",
        forgejo_url=forgejo_base,
        forgejo_token="tok",
    )

    result = publish_mcp_artifact(artifact, archive, cfg)

    assert result.tag == "v1.2.3"
    release = ForgejoClient(cfg.forgejo_url, "tok").get_release_by_tag("approved", "echo", "v1.2.3")
    assert release is not None
    assert sorted(asset.name.rsplit(".", 2)[-1] for asset in release.assets)
    assert {asset.name for asset in release.assets} == {
        "approved-echo-1.2.3.tar.gz", "approved-echo-1.2.3.sha256", "approved-echo-1.2.3.artifact.json",
    }


def test_publish_mcp_never_mutates_existing_published_release(fake_forgejo, tmp_path: Path) -> None:
    archive = tmp_path / "mcp.tar.gz"
    archive.write_bytes(b"approved mcp")
    checksum = sha256_file(archive)
    forgejo_base = f"http://127.0.0.1:{fake_forgejo.server_port}"
    metadata = {
        "schemaVersion": 1, "artifactKind": "mcp", "namespace": "approved", "name": "echo",
        "version": "1.2.3", "forgejoRelease": "v1.2.3", "commit": "b" * 40,
        "checksum": checksum, "license": "MIT",
        "source": f"{forgejo_base}/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz",
        "transport": "stdio", "command": ["/opt/skillify/mcp/echo/bin/server"], "environment": [],
        "permissions": {"readPaths": [], "writePaths": [], "commands": {}, "networkDomains": [], "mcpServers": [], "databaseResources": [], "unattended": False, "confirm": []},
        "enabled": True,
    }
    client = ForgejoClient(forgejo_base, "tok")
    client.ensure_org_repo("approved", "echo")
    client.create_release(
        "approved", "echo", tag_name="v1.2.3", name="echo 1.2.3",
        body=f"artifactKind=mcp\ncoordinate=mcp:approved/echo@1.2.3\nsha256={checksum}",
    )
    cfg = SkillifyConfig(home=tmp_path / "home", forgejo_url=client.base_url, forgejo_token="tok")

    with pytest.raises(AlreadyPublishedError):
        publish_mcp_artifact(
            load_mcp_artifact(metadata, approved_forgejo_base=forgejo_base), archive, cfg
        )

    release = client.get_release_by_tag("approved", "echo", "v1.2.3")
    assert release is not None and release.assets == []


def test_publish_mcp_rejects_corrupted_same_name_asset_in_draft(fake_forgejo, tmp_path: Path) -> None:
    archive = tmp_path / "mcp.tar.gz"
    archive.write_bytes(b"approved mcp")
    checksum = sha256_file(archive)
    forgejo_base = f"http://127.0.0.1:{fake_forgejo.server_port}"
    metadata = {
        "schemaVersion": 1, "artifactKind": "mcp", "namespace": "approved", "name": "echo",
        "version": "1.2.3", "forgejoRelease": "v1.2.3", "commit": "b" * 40,
        "checksum": checksum, "license": "MIT",
        "source": f"{forgejo_base}/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz",
        "transport": "stdio", "command": ["/opt/skillify/mcp/echo/bin/server"], "environment": [],
        "permissions": {"readPaths": [], "writePaths": [], "commands": {}, "networkDomains": [], "mcpServers": [], "databaseResources": [], "unattended": False, "confirm": []},
        "enabled": True,
    }
    client = ForgejoClient(forgejo_base, "tok")
    client.ensure_org_repo("approved", "echo")
    release = client.create_release(
        "approved", "echo", tag_name="v1.2.3", name="echo 1.2.3",
        body=f"artifactKind=mcp\ncoordinate=mcp:approved/echo@1.2.3\nsha256={checksum}", draft=True,
    )
    corrupt = tmp_path / "approved-echo-1.2.3.artifact.json"
    corrupt.write_text('{"artifactKind":"skill"}\n', encoding="utf-8")
    client.upload_release_asset("approved", "echo", release.id, corrupt)
    cfg = SkillifyConfig(home=tmp_path / "home", forgejo_url=client.base_url, forgejo_token="tok")

    with pytest.raises(AlreadyPublishedError):
        publish_mcp_artifact(
            load_mcp_artifact(metadata, approved_forgejo_base=forgejo_base), archive, cfg
        )

    recovered = client.find_release_by_tag("approved", "echo", "v1.2.3")
    assert recovered is not None and recovered.draft is True


def test_publish_mcp_rejects_source_or_organization_coordinate_before_network(
    fake_forgejo, tmp_path: Path
) -> None:
    archive = tmp_path / "mcp.tar.gz"
    archive.write_bytes(b"approved mcp")
    base = f"http://127.0.0.1:{fake_forgejo.server_port}"
    metadata = {
        "schemaVersion": 1, "artifactKind": "mcp", "namespace": "approved", "name": "echo",
        "version": "1.2.3", "forgejoRelease": "v1.2.3", "commit": "b" * 40,
        "checksum": sha256_file(archive), "license": "MIT",
        "source": f"{base}/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz",
        "transport": "stdio", "command": ["/opt/skillify/mcp/echo/bin/server"],
        "environment": [], "permissions": {"readPaths": [], "writePaths": [], "commands": {}, "networkDomains": [], "mcpServers": [], "databaseResources": [], "unattended": False, "confirm": []},
        "enabled": True,
    }
    artifact = load_mcp_artifact(metadata, approved_forgejo_base=base)
    cfg = SkillifyConfig(
        home=tmp_path / "home", forgejo_url=base, forgejo_token="tok", forgejo_org="attacker"
    )

    with pytest.raises(McpRegistryError, match="coordinate"):
        publish_mcp_artifact(artifact, archive, cfg)
    assert fake_forgejo.state.repos == set()


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("wrong", "artifactKind=mcp\ncoordinate=mcp:approved/echo@1.2.3\nsha256={checksum}"),
        ("echo 1.2.3", "artifactKind=skill\ncoordinate=mcp:approved/echo@1.2.3\nsha256={checksum}"),
        ("echo 1.2.3", "artifactKind=mcp\ncoordinate=mcp:approved/echo@1.2.3\nsha256={checksum}"),
    ],
)
def test_publish_mcp_rejects_nonexact_or_incomplete_draft_without_mutation(
    fake_forgejo, tmp_path: Path, name: str, body: str
) -> None:
    archive = tmp_path / "mcp.tar.gz"
    archive.write_bytes(b"approved mcp")
    checksum = sha256_file(archive)
    base = f"http://127.0.0.1:{fake_forgejo.server_port}"
    metadata = {
        "schemaVersion": 1, "artifactKind": "mcp", "namespace": "approved", "name": "echo",
        "version": "1.2.3", "forgejoRelease": "v1.2.3", "commit": "b" * 40,
        "checksum": checksum, "license": "MIT",
        "source": f"{base}/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz",
        "transport": "stdio", "command": ["/opt/skillify/mcp/echo/bin/server"], "environment": [],
        "permissions": {"readPaths": [], "writePaths": [], "commands": {}, "networkDomains": [], "mcpServers": [], "databaseResources": [], "unattended": False, "confirm": []}, "enabled": True,
    }
    client = ForgejoClient(base, "tok")
    client.ensure_org_repo("approved", "echo")
    release = client.create_release(
        "approved", "echo", tag_name="v1.2.3", name=name,
        body=body.format(checksum=checksum), draft=True,
    )
    before = dict(fake_forgejo.state.releases["approved/echo/v1.2.3"])
    cfg = SkillifyConfig(home=tmp_path / "home", forgejo_url=base, forgejo_token="tok")

    with pytest.raises(AlreadyPublishedError):
        publish_mcp_artifact(
            load_mcp_artifact(metadata, approved_forgejo_base=base), archive, cfg
        )

    after = fake_forgejo.state.releases["approved/echo/v1.2.3"]
    assert after == before
    assert after["id"] == release.id and after["assets"] == []


@pytest.mark.parametrize("corrupt_sidecar", [False, True])
def test_publish_mcp_recovers_only_complete_byte_exact_draft(
    fake_forgejo, tmp_path: Path, corrupt_sidecar: bool
) -> None:
    archive = tmp_path / "mcp.tar.gz"
    archive.write_bytes(b"approved mcp")
    checksum = sha256_file(archive)
    base = f"http://127.0.0.1:{fake_forgejo.server_port}"
    metadata = {
        "schemaVersion": 1, "artifactKind": "mcp", "namespace": "approved", "name": "echo",
        "version": "1.2.3", "forgejoRelease": "v1.2.3", "commit": "b" * 40,
        "checksum": checksum, "license": "MIT",
        "source": f"{base}/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz",
        "transport": "stdio", "command": ["/opt/skillify/mcp/echo/bin/server"], "environment": [],
        "permissions": {"readPaths": [], "writePaths": [], "commands": {}, "networkDomains": [], "mcpServers": [], "databaseResources": [], "unattended": False, "confirm": []}, "enabled": True,
    }
    artifact = load_mcp_artifact(metadata, approved_forgejo_base=base)
    cfg = SkillifyConfig(home=tmp_path / "home", forgejo_url=base, forgejo_token="tok")
    packed = pack_mcp(artifact, archive, tmp_path / "prepared")
    client = ForgejoClient(base, "tok")
    client.ensure_org_repo("approved", "echo")
    release = client.create_release(
        "approved", "echo", tag_name="v1.2.3", name="echo 1.2.3",
        body=f"artifactKind=mcp\ncoordinate=mcp:approved/echo@1.2.3\nsha256={checksum}",
        draft=True,
    )
    assets = [packed.tarball_path, packed.checksum_path, packed.artifact_manifest_path]
    if corrupt_sidecar:
        corrupt = tmp_path / packed.artifact_manifest_path.name
        corrupt.write_text('{"artifactKind":"skill"}\n', encoding="utf-8")
        assets[-1] = corrupt
    for asset in assets:
        client.upload_release_asset("approved", "echo", release.id, asset)

    if corrupt_sidecar:
        with pytest.raises(AlreadyPublishedError):
            publish_mcp_artifact(artifact, archive, cfg)
        unchanged = client.find_release_by_tag("approved", "echo", "v1.2.3")
        assert unchanged is not None and unchanged.draft is True
    else:
        result = publish_mcp_artifact(artifact, archive, cfg)
        assert result.recovered is True
        published = client.find_release_by_tag("approved", "echo", "v1.2.3")
        assert published is not None and published.draft is False
