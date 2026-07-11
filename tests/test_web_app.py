"""Tests for T3.1 — the community-site FastAPI backend (list/detail/search/install-info).

M-A (docs/review-m2-m6.md): the whole market now requires a logged-in Keycloak user,
including these read endpoints — every request in this file authenticates with a fake
Keycloak token (tests/fake_keycloak.py), plus one test confirms anonymous reads are 401.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.ingest import ReleaseEvent, upsert_release
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
                namespace="text", name="word-frequency", version="1.0.0",
                description="Count word frequency in text.", author="Skillify examples",
                tags=["text"], checksum="b" * 64,
                release_url="http://forgejo.local/text/word-frequency/releases/tag/v1.0.0",
                published_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
        )
    return url


def _configure_keycloak(monkeypatch, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")


def _auth_headers(fake_keycloak) -> dict[str, str]:
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    return {"Authorization": f"Bearer {token}"}


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_list_skills_requires_auth(monkeypatch, tmp_path: Path, index_db_url: str, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    _configure_keycloak(monkeypatch, fake_keycloak)

    resp = client.get("/api/skills")
    assert resp.status_code == 401


def test_list_skills_requires_index_configured(monkeypatch, tmp_path: Path, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SKILLIFY_INDEX_DB_URL", raising=False)
    _configure_keycloak(monkeypatch, fake_keycloak)

    resp = client.get("/api/skills", headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 503


def test_list_skills(monkeypatch, tmp_path: Path, index_db_url: str, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    _configure_keycloak(monkeypatch, fake_keycloak)

    resp = client.get("/api/skills", headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 200
    body = resp.json()
    # C-4: /api/skills now returns a SearchResult pagination wrapper, not a bare list.
    names = {s["name"] for s in body["items"]}
    assert names == {"pivot-analysis", "word-frequency"}
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["pageSize"] == 20


def test_search_skills(monkeypatch, tmp_path: Path, index_db_url: str, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    _configure_keycloak(monkeypatch, fake_keycloak)

    resp = client.get("/api/search", params={"q": "pivot"}, headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 200
    body = resp.json()
    names = {s["name"] for s in body["items"]}
    assert names == {"pivot-analysis"}
    assert body["total"] == 1


def test_skill_detail_not_found(monkeypatch, tmp_path: Path, index_db_url: str, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    _configure_keycloak(monkeypatch, fake_keycloak)

    resp = client.get("/api/skills/nope/nothing", headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 404


def test_skill_detail_without_forgejo_configured(monkeypatch, tmp_path: Path, index_db_url: str, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    monkeypatch.delenv("SKILLIFY_FORGEJO_URL", raising=False)
    _configure_keycloak(monkeypatch, fake_keycloak)

    resp = client.get("/api/skills/excel/pivot-analysis", headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "0.1.0"
    assert body["versions"] == ["0.1.0"]
    assert body["readme"] is None
    assert body["tarballUrl"] is None
    assert body["installCommand"] == "skillctl install excel/pivot-analysis"


def test_skill_detail_enriched_from_forgejo(monkeypatch, tmp_path: Path, index_db_url: str, fake_forgejo, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    _configure_keycloak(monkeypatch, fake_keycloak)

    fake_forgejo.state.raw_files["excel/pivot-analysis/v0.1.0/README.md"] = "# Pivot Analysis\n"
    fake_forgejo.state.raw_files["excel/pivot-analysis/v0.1.0/SKILL.md"] = "---\nname: pivot-analysis\n---\n"

    setup_client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")
    setup_client.ensure_org_repo("excel", "pivot-analysis")
    release = setup_client.create_release("excel", "pivot-analysis", tag_name="v0.1.0", name="v0.1.0")
    tarball = tmp_path / "excel-pivot-analysis-0.1.0.tar.gz"
    tarball.write_bytes(b"x")
    setup_client.upload_release_asset("excel", "pivot-analysis", release.id, tarball)
    checksum = tmp_path / "excel-pivot-analysis-0.1.0.sha256"
    checksum.write_text("deadbeef\n", encoding="utf-8")
    setup_client.upload_release_asset("excel", "pivot-analysis", release.id, checksum)

    resp = client.get("/api/skills/excel/pivot-analysis", headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 200
    body = resp.json()
    assert body["readme"] == "# Pivot Analysis\n"
    assert body["skillMd"].startswith("---")
    assert body["tarballUrl"] and body["tarballUrl"].endswith("excel-pivot-analysis-0.1.0.tar.gz")
    assert body["checksumUrl"] and body["checksumUrl"].endswith("excel-pivot-analysis-0.1.0.sha256")


def test_skill_detail_reflects_current_user_star_and_subscription(
    monkeypatch, tmp_path: Path, index_db_url: str, fake_keycloak
) -> None:
    """C-5 gap fix: `starred`/`subscribed` on `SkillDetail` must reflect the CURRENTLY
    authenticated user, and `starCount` must be accurate — this is what lets the frontend
    render the star/subscribe buttons correctly on first page load, before any toggle."""
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    monkeypatch.delenv("SKILLIFY_FORGEJO_URL", raising=False)
    _configure_keycloak(monkeypatch, fake_keycloak)

    jane_headers = _auth_headers(fake_keycloak)
    bob_token = fake_keycloak.mint_token(audience="skillify-web", subject="bob")
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # Before any star/subscribe: both users see false/false, count 0.
    resp = client.get("/api/skills/excel/pivot-analysis", headers=jane_headers)
    body = resp.json()
    assert body["starred"] is False
    assert body["subscribed"] is False
    assert body["starCount"] == 0

    client.post("/api/skills/excel/pivot-analysis/star", headers=jane_headers)
    client.post("/api/skills/excel/pivot-analysis/subscription", headers=jane_headers)
    client.post("/api/skills/excel/pivot-analysis/star", headers=bob_headers)

    resp = client.get("/api/skills/excel/pivot-analysis", headers=jane_headers)
    body = resp.json()
    assert body["starred"] is True
    assert body["subscribed"] is True
    assert body["starCount"] == 2

    # bob starred but never subscribed — sees his own star state, not jane's subscription.
    resp = client.get("/api/skills/excel/pivot-analysis", headers=bob_headers)
    body = resp.json()
    assert body["starred"] is True
    assert body["subscribed"] is False
    assert body["starCount"] == 2


def test_install_info(monkeypatch, fake_keycloak) -> None:
    _configure_keycloak(monkeypatch, fake_keycloak)
    resp = client.get("/api/skills/excel/pivot-analysis/install", headers=_auth_headers(fake_keycloak))
    assert resp.status_code == 200
    body = resp.json()
    assert body["installCommand"] == "skillctl install excel/pivot-analysis"
    assert "excel/pivot-analysis" in body["agentPrompt"]


def test_install_info_requires_auth(monkeypatch, fake_keycloak) -> None:
    _configure_keycloak(monkeypatch, fake_keycloak)
    resp = client.get("/api/skills/excel/pivot-analysis/install")
    assert resp.status_code == 401
