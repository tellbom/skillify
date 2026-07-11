"""Tests for C-1 web endpoints: version timeline, ?version= detail, yank/unyank, diff.

Follows tests/test_web_app.py's fixture pattern (SQLite index DB + fake Keycloak + fake
Forgejo where needed).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.ingest import ReleaseEvent, upsert_release
from skillify.index.models import SkillNamespaceOwner
from skillify.publish.forgejo_client import ForgejoClient
from skillify.web.app import app
from tests.fake_forgejo import fake_forgejo  # noqa: F401
from tests.fake_keycloak import fake_keycloak  # noqa: F401

client = TestClient(app)


@pytest.fixture()
def index_db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'index.db').as_posix()}"
    engine = make_engine(url)
    init_db(engine)
    with session_scope(engine) as session:
        upsert_release(
            session,
            ReleaseEvent(
                namespace="excel", name="pivot-analysis", version="0.1.0",
                description="Build pivot tables from tabular data.", author="Jane Doe",
                tags=["excel", "data"], checksum="a" * 64,
                release_url="http://forgejo.local/excel/pivot-analysis/releases/tag/v0.1.0",
                published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        )
        upsert_release(
            session,
            ReleaseEvent(
                namespace="excel", name="pivot-analysis", version="0.2.0",
                description="Build pivot tables from tabular data, v2.", author="Jane Doe",
                tags=["excel", "data"], checksum="b" * 64,
                release_url="http://forgejo.local/excel/pivot-analysis/releases/tag/v0.2.0",
                published_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            ),
        )
    return url


def _configure_keycloak(monkeypatch, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")


def _auth_headers(fake_keycloak, subject: str = "jane") -> dict[str, str]:
    token = fake_keycloak.mint_token(audience="skillify-web", subject=subject)
    return {"Authorization": f"Bearer {token}"}


def _configure_common(monkeypatch, tmp_path: Path, index_db_url: str, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    _configure_keycloak(monkeypatch, fake_keycloak)


def test_versions_endpoint_lists_all_with_yank_status(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    monkeypatch.delenv("SKILLIFY_FORGEJO_URL", raising=False)

    resp = client.get("/api/skills/excel/pivot-analysis/versions", headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 200
    body = resp.json()
    assert {v["version"] for v in body} == {"0.1.0", "0.2.0"}
    assert all(v["yanked"] is False for v in body)
    assert all(v["releaseNotes"] is None for v in body)  # Forgejo not configured


def test_versions_endpoint_not_found(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.get("/api/skills/nope/nothing/versions", headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 404


def test_versions_endpoint_pulls_release_notes_from_forgejo(
    monkeypatch, tmp_path, index_db_url, fake_forgejo, fake_keycloak
) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")

    setup_client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")
    setup_client.ensure_org_repo("excel", "pivot-analysis")
    setup_client.create_release("excel", "pivot-analysis", tag_name="v0.1.0", name="v0.1.0", body="first cut")
    setup_client.create_release("excel", "pivot-analysis", tag_name="v0.2.0", name="v0.2.0", body="bugfixes")

    resp = client.get("/api/skills/excel/pivot-analysis/versions", headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 200
    notes = {v["version"]: v["releaseNotes"] for v in resp.json()}
    assert notes == {"0.1.0": "first cut", "0.2.0": "bugfixes"}


def test_skill_detail_with_explicit_version_bypasses_yanked(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    monkeypatch.delenv("SKILLIFY_FORGEJO_URL", raising=False)

    yank_resp = client.post(
        "/api/skills/excel/pivot-analysis/versions/0.2.0/yank", headers=_auth_headers(fake_keycloak, subject="Jane Doe")
    )
    assert yank_resp.status_code == 200
    assert yank_resp.json() == {"version": "0.2.0", "yanked": True}

    # Default detail (no ?version=) falls back to the newest non-yanked version.
    resp = client.get("/api/skills/excel/pivot-analysis", headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 200
    assert resp.json()["version"] == "0.1.0"

    # Explicit ?version=0.2.0 still resolves even though it's yanked.
    resp = client.get(
        "/api/skills/excel/pivot-analysis", params={"version": "0.2.0"}, headers=_auth_headers(fake_keycloak)
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == "0.2.0"


def test_skill_detail_with_unknown_version_is_404(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.get(
        "/api/skills/excel/pivot-analysis", params={"version": "9.9.9"}, headers=_auth_headers(fake_keycloak)
    )
    assert resp.status_code == 404


def test_yank_requires_auth(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.post("/api/skills/excel/pivot-analysis/versions/0.1.0/yank")
    assert resp.status_code == 401


def test_yank_by_author_succeeds(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.post(
        "/api/skills/excel/pivot-analysis/versions/0.1.0/yank",
        headers=_auth_headers(fake_keycloak, subject="Jane Doe"),
    )
    assert resp.status_code == 200
    assert resp.json() == {"version": "0.1.0", "yanked": True}


def test_yank_by_non_author_non_owner_is_403(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.post(
        "/api/skills/excel/pivot-analysis/versions/0.1.0/yank",
        headers=_auth_headers(fake_keycloak, subject="random-stranger"),
    )
    assert resp.status_code == 403


def test_yank_by_namespace_owner_succeeds(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    engine = make_engine(index_db_url)
    with session_scope(engine) as session:
        session.add(
            SkillNamespaceOwner(
                namespace="excel", owner_username="ns-owner", claimed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
            )
        )

    resp = client.post(
        "/api/skills/excel/pivot-analysis/versions/0.1.0/yank",
        headers=_auth_headers(fake_keycloak, subject="ns-owner"),
    )
    assert resp.status_code == 200
    assert resp.json()["yanked"] is True


def test_yank_unknown_version_is_404(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.post(
        "/api/skills/excel/pivot-analysis/versions/9.9.9/yank",
        headers=_auth_headers(fake_keycloak, subject="Jane Doe"),
    )
    assert resp.status_code == 404


def test_unyank_restores_visibility_in_list_and_detail(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    monkeypatch.delenv("SKILLIFY_FORGEJO_URL", raising=False)

    auth = _auth_headers(fake_keycloak, subject="Jane Doe")
    client.post("/api/skills/excel/pivot-analysis/versions/0.2.0/yank", headers=auth)

    resp = client.get("/api/skills/excel/pivot-analysis", headers=_auth_headers(fake_keycloak))
    assert resp.json()["version"] == "0.1.0"

    unyank_resp = client.post("/api/skills/excel/pivot-analysis/versions/0.2.0/unyank", headers=auth)
    assert unyank_resp.status_code == 200
    assert unyank_resp.json() == {"version": "0.2.0", "yanked": False}

    resp = client.get("/api/skills/excel/pivot-analysis", headers=_auth_headers(fake_keycloak))
    assert resp.json()["version"] == "0.2.0"


def test_diff_endpoint_without_forgejo_configured_is_400(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    monkeypatch.delenv("SKILLIFY_FORGEJO_URL", raising=False)
    resp = client.get(
        "/api/skills/excel/pivot-analysis/diff",
        params={"from": "0.1.0", "to": "0.2.0"},
        headers=_auth_headers(fake_keycloak),
    )
    assert resp.status_code == 400


def test_diff_endpoint_unknown_version_is_404(monkeypatch, tmp_path, index_db_url, fake_forgejo, fake_keycloak) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    resp = client.get(
        "/api/skills/excel/pivot-analysis/diff",
        params={"from": "0.1.0", "to": "9.9.9"},
        headers=_auth_headers(fake_keycloak),
    )
    assert resp.status_code == 404


def test_diff_endpoint_computes_added_removed_modified(
    monkeypatch, tmp_path, index_db_url, fake_forgejo, fake_keycloak
) -> None:
    _configure_common(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")

    fake_forgejo.state.trees["excel/pivot-analysis/v0.1.0"] = [
        {"path": "SKILL.md", "sha": "sha-skill-v1", "type": "blob"},
        {"path": "skill.yaml", "sha": "sha-yaml-v1", "type": "blob"},
        {"path": "removed.txt", "sha": "sha-removed", "type": "blob"},
    ]
    fake_forgejo.state.trees["excel/pivot-analysis/v0.2.0"] = [
        {"path": "SKILL.md", "sha": "sha-skill-v2", "type": "blob"},  # modified
        {"path": "skill.yaml", "sha": "sha-yaml-v1", "type": "blob"},  # unchanged
        {"path": "added.txt", "sha": "sha-added", "type": "blob"},  # added
    ]

    resp = client.get(
        "/api/skills/excel/pivot-analysis/diff",
        params={"from": "0.1.0", "to": "0.2.0"},
        headers=_auth_headers(fake_keycloak),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"added": ["added.txt"], "removed": ["removed.txt"], "modified": ["SKILL.md"]}
