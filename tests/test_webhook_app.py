"""Tests for T2.1c — the webhook FastAPI app (signature verification, push/tag handling)."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skillify.webhook.app import app
from skillify.webhook.verify import verify_forgejo_signature
from tests.fake_forgejo import fake_forgejo  # noqa: F401

client = TestClient(app)


def _make_archive_bytes(manifest_yaml: str, skill_md: str = "---\nname: pivot-analysis\ndescription: x\n---\nbody\n") -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name, content in {"SKILL.md": skill_md.encode(), "skill.yaml": manifest_yaml.encode()}.items():
                info = tarfile.TarInfo(name=f"pivot-analysis-src/{name}")
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


_VALID_MANIFEST_YAML = (
    "manifestVersion: 1\nnamespace: excel\nname: pivot-analysis\nversion: 0.1.0\n"
    "description: x\nauthor: t\nlicense: MIT\nruntime: claude-agent-skill\ntargets: [claude]\n"
)


def _push_payload(*, ref: str, owner: str = "excel", repo: str = "pivot-analysis") -> dict:
    return {"ref": ref, "repository": {"name": repo, "owner": {"username": owner}}}


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_branch_push_is_ignored(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")

    resp = client.post("/webhook/forgejo", json=_push_payload(ref="refs/heads/main"))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_tag_push_publishes_release(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    fake_forgejo.state.archives["excel/pivot-analysis/v0.1.0"] = _make_archive_bytes(_VALID_MANIFEST_YAML)

    resp = client.post("/webhook/forgejo", json=_push_payload(ref="refs/tags/v0.1.0"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "published"
    assert body["org"] == "excel"
    assert body["repo"] == "pivot-analysis"
    assert body["tag"] == "v0.1.0"
    assert body["releaseUrl"]

    from skillify.publish.forgejo_client import ForgejoClient

    verify_client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")
    release = verify_client.get_release_by_tag("excel", "pivot-analysis", "v0.1.0")
    assert release is not None
    asset_names = {a.name for a in release.assets}
    assert "excel-pivot-analysis-0.1.0.tar.gz" in asset_names


def test_repush_same_tag_is_ignored_not_error(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    fake_forgejo.state.archives["excel/pivot-analysis/v0.1.0"] = _make_archive_bytes(_VALID_MANIFEST_YAML)

    first = client.post("/webhook/forgejo", json=_push_payload(ref="refs/tags/v0.1.0"))
    assert first.json()["status"] == "published"

    second = client.post("/webhook/forgejo", json=_push_payload(ref="refs/tags/v0.1.0"))
    assert second.status_code == 200
    assert second.json()["status"] == "ignored"


def test_tag_version_mismatch_is_rejected(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    # Tag says v0.2.0 but skill.yaml still declares 0.1.0.
    fake_forgejo.state.archives["excel/pivot-analysis/v0.2.0"] = _make_archive_bytes(_VALID_MANIFEST_YAML)

    resp = client.post("/webhook/forgejo", json=_push_payload(ref="refs/tags/v0.2.0"))
    assert resp.status_code == 422
    assert "does not match" in resp.json()["detail"]


def test_path_traversal_via_repo_owner_is_rejected(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    """M-G (docs/review-m2-m6.md): repository.owner.username feeds work_dir's path — a
    crafted payload must be rejected before it's ever joined onto a filesystem path."""
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")

    resp = client.post(
        "/webhook/forgejo", json=_push_payload(ref="refs/tags/v0.1.0", owner="../../evil")
    )
    assert resp.status_code == 422
    assert "not a safe path segment" in resp.json()["detail"]


def test_path_traversal_via_repo_name_is_rejected(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")

    resp = client.post(
        "/webhook/forgejo", json=_push_payload(ref="refs/tags/v0.1.0", repo="../../evil")
    )
    assert resp.status_code == 422
    assert "not a safe path segment" in resp.json()["detail"]


def test_path_traversal_via_tag_version_is_rejected(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")

    resp = client.post("/webhook/forgejo", json=_push_payload(ref="refs/tags/v../../evil"))
    assert resp.status_code == 422
    assert "not a safe path segment" in resp.json()["detail"]


def test_signature_required_when_secret_configured(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    monkeypatch.setenv("SKILLIFY_WEBHOOK_SECRET", "s3cret")

    resp = client.post("/webhook/forgejo", json=_push_payload(ref="refs/heads/main"))
    assert resp.status_code == 401


def test_signature_valid_is_accepted(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    monkeypatch.setenv("SKILLIFY_WEBHOOK_SECRET", "s3cret")

    import hashlib
    import hmac

    body = json.dumps(_push_payload(ref="refs/heads/main")).encode("utf-8")
    signature = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()

    resp = client.post(
        "/webhook/forgejo",
        content=body,
        headers={"Content-Type": "application/json", "X-Forgejo-Signature": signature},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_verify_forgejo_signature_helper() -> None:
    secret = "topsecret"
    body = b'{"ref":"refs/heads/main"}'
    import hashlib
    import hmac

    good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_forgejo_signature(body, good_sig, secret) is True
    assert verify_forgejo_signature(body, f"sha256={good_sig}", secret) is True
    assert verify_forgejo_signature(body, "wrong", secret) is False
    assert verify_forgejo_signature(body, None, secret) is False
