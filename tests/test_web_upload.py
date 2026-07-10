"""Tests for T4.2 — the web upload endpoint (Keycloak-gated, validates + publishes)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skillify.publish.forgejo_client import ForgejoClient
from skillify.web.app import app
from tests.fake_forgejo import fake_forgejo  # noqa: F401
from tests.fake_keycloak import fake_keycloak  # noqa: F401

client = TestClient(app)

_VALID_MANIFEST = (
    "manifestVersion: 1\nnamespace: excel\nname: pivot-analysis\nversion: 0.1.0\n"
    "description: Build pivot tables from tabular data.\nauthor: Jane Doe\nlicense: MIT\n"
    "runtime: claude-agent-skill\ntargets: [claude]\n"
)
_VALID_SKILL_MD = "---\nname: pivot-analysis\ndescription: x\n---\nbody\n"


def _make_zip(files: dict[str, bytes], *, wrap_dir: str | None = "my-upload") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            arcname = f"{wrap_dir}/{name}" if wrap_dir else name
            zf.writestr(arcname, content)
    return buf.getvalue()


def _configure(monkeypatch, tmp_path: Path, fake_forgejo, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", f"sqlite:///{(tmp_path / 'index.db').as_posix()}")


def test_upload_requires_auth(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    zip_bytes = _make_zip({"SKILL.md": _VALID_SKILL_MD.encode(), "skill.yaml": _VALID_MANIFEST.encode()})

    resp = client.post("/api/skills/upload", files={"file": ("upload.zip", zip_bytes, "application/zip")})
    assert resp.status_code == 401


def test_upload_rejects_non_zip(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")

    resp = client.post(
        "/api/skills/upload",
        files={"file": ("upload.txt", b"not a zip", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_upload_valid_skill_publishes(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    zip_bytes = _make_zip({"SKILL.md": _VALID_SKILL_MD.encode(), "skill.yaml": _VALID_MANIFEST.encode()})

    resp = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", zip_bytes, "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["namespace"] == "excel"
    assert body["name"] == "pivot-analysis"
    assert body["version"] == "0.1.0"
    assert body["releaseUrl"]

    verify_client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")
    release = verify_client.get_release_by_tag("excel", "pivot-analysis", "v0.1.0")
    assert release is not None
    assert "excel-pivot-analysis-0.1.0.tar.gz" in {a.name for a in release.assets}


def test_upload_invalid_skill_returns_structured_issues(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    # Missing SKILL.md entirely.
    zip_bytes = _make_zip({"skill.yaml": _VALID_MANIFEST.encode()})

    resp = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", zip_bytes, "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    issues = resp.json()["detail"]
    assert any("SKILL.md" in issue["path"] for issue in issues)


def test_upload_duplicate_version_conflicts(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    zip_bytes = _make_zip({"SKILL.md": _VALID_SKILL_MD.encode(), "skill.yaml": _VALID_MANIFEST.encode()})

    first = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", zip_bytes, "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", zip_bytes, "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 409


def test_upload_rejects_namespace_owned_by_another_user(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    """M-C (docs/review-m2-m6.md): first upload into a namespace claims it for that
    Keycloak user; a different user publishing into the same namespace is rejected even
    though the manifest itself declares no conflicting name/version."""
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    jane = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    bob = fake_keycloak.mint_token(audience="skillify-web", subject="bob")

    jane_zip = _make_zip({"SKILL.md": _VALID_SKILL_MD.encode(), "skill.yaml": _VALID_MANIFEST.encode()})
    first = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", jane_zip, "application/zip")},
        headers={"Authorization": f"Bearer {jane}"},
    )
    assert first.status_code == 200, first.text

    bobs_manifest = _VALID_MANIFEST.replace("name: pivot-analysis", "name: another-skill")
    bob_zip = _make_zip({"SKILL.md": _VALID_SKILL_MD.encode(), "skill.yaml": bobs_manifest.encode()})
    second = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", bob_zip, "application/zip")},
        headers={"Authorization": f"Bearer {bob}"},
    )
    assert second.status_code == 403


def test_upload_same_user_can_republish_own_namespace(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    jane = fake_keycloak.mint_token(audience="skillify-web", subject="jane")

    first_zip = _make_zip({"SKILL.md": _VALID_SKILL_MD.encode(), "skill.yaml": _VALID_MANIFEST.encode()})
    first = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", first_zip, "application/zip")},
        headers={"Authorization": f"Bearer {jane}"},
    )
    assert first.status_code == 200, first.text

    second_manifest = _VALID_MANIFEST.replace("name: pivot-analysis", "name: another-skill")
    second_zip = _make_zip({"SKILL.md": _VALID_SKILL_MD.encode(), "skill.yaml": second_manifest.encode()})
    second = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", second_zip, "application/zip")},
        headers={"Authorization": f"Bearer {jane}"},
    )
    assert second.status_code == 200, second.text


def test_upload_rejects_when_index_not_configured(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    monkeypatch.delenv("SKILLIFY_INDEX_DB_URL", raising=False)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    zip_bytes = _make_zip({"SKILL.md": _VALID_SKILL_MD.encode(), "skill.yaml": _VALID_MANIFEST.encode()})

    resp = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", zip_bytes, "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503


def test_upload_rejects_oversized_raw_body(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    """M-D (docs/review-m2-m6.md): the raw upload is capped well before extraction."""
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    monkeypatch.setenv("SKILLIFY_MAX_UPLOAD_BYTES", "1024")
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    zip_bytes = _make_zip({"SKILL.md": _VALID_SKILL_MD.encode(), "skill.yaml": _VALID_MANIFEST.encode()})
    oversized = zip_bytes + (b"\x00" * 2048)  # padding after the zip's own bytes, still > cap

    resp = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", oversized, "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 413


def test_upload_rejects_zip_bomb_decompressed_size(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    """M-D: a small compressed archive that expands past max_extracted_bytes is rejected."""
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    monkeypatch.setenv("SKILLIFY_MAX_EXTRACTED_BYTES", "1024")
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("my-upload/SKILL.md", _VALID_SKILL_MD)
        zf.writestr("my-upload/skill.yaml", _VALID_MANIFEST)
        zf.writestr("my-upload/resources/big.bin", b"0" * (2 * 1024 * 1024))  # compresses tiny, expands big

    resp = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", buf.getvalue(), "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_upload_rejects_too_many_files(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    """M-D: entry-count cap, independent of total decompressed size."""
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    monkeypatch.setenv("SKILLIFY_MAX_EXTRACTED_FILES", "5")
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("my-upload/SKILL.md", _VALID_SKILL_MD)
        zf.writestr("my-upload/skill.yaml", _VALID_MANIFEST)
        for i in range(20):
            zf.writestr(f"my-upload/resources/file{i}.txt", "x")

    resp = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", buf.getvalue(), "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_upload_rejects_path_traversal_zip(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.txt", "pwned")
    resp = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", buf.getvalue(), "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_upload_rejects_path_traversal_via_manifest_name(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    """M-B (docs/review-m2-m6.md): a crafted skill.yaml `name` field must not be able to
    move the extracted tree outside the upload work_dir."""
    _configure(monkeypatch, tmp_path, fake_forgejo, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    manifest = _VALID_MANIFEST.replace("name: pivot-analysis", "name: ../../evil")
    zip_bytes = _make_zip({"SKILL.md": _VALID_SKILL_MD.encode(), "skill.yaml": manifest.encode()})

    resp = client.post(
        "/api/skills/upload",
        files={"file": ("upload.zip", zip_bytes, "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    issues = resp.json()["detail"]
    assert any("name" in issue["path"] for issue in issues)
