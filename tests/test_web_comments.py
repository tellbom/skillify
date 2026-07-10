"""Tests for T5.1 — skill comments.

M-A (docs/review-m2-m6.md): reads now require a Keycloak session too, not just writes
(the market-wide login requirement) — this superseded the original "public read" design.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from skillify.index.db import init_db, make_engine
from skillify.web.app import app
from tests.fake_keycloak import fake_keycloak  # noqa: F401

client = TestClient(app)


def _configure(monkeypatch, tmp_path: Path, fake_keycloak) -> str:
    index_db_url = f"sqlite:///{(tmp_path / 'index.db').as_posix()}"
    init_db(make_engine(index_db_url))
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")
    return index_db_url


def test_post_comment_requires_auth(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    resp = client.post("/api/skills/excel/pivot-analysis/comments", json={"body": "nice skill"})
    assert resp.status_code == 401


def test_get_comments_requires_auth(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    resp = client.get("/api/skills/excel/pivot-analysis/comments")
    assert resp.status_code == 401


def test_post_and_list_comments(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")

    post_resp = client.post(
        "/api/skills/excel/pivot-analysis/comments",
        json={"body": "works great, thanks!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert post_resp.status_code == 200, post_resp.text
    body = post_resp.json()
    assert body["author"] == "jane"
    assert body["body"] == "works great, thanks!"

    list_resp = client.get(
        "/api/skills/excel/pivot-analysis/comments", headers={"Authorization": f"Bearer {token}"}
    )
    assert list_resp.status_code == 200
    comments = list_resp.json()
    assert len(comments) == 1
    assert comments[0]["body"] == "works great, thanks!"


def test_empty_comment_rejected(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")

    resp = client.post(
        "/api/skills/excel/pivot-analysis/comments",
        json={"body": "   "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_comments_scoped_per_skill(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")

    client.post(
        "/api/skills/excel/pivot-analysis/comments", json={"body": "on pivot"},
        headers={"Authorization": f"Bearer {token}"},
    )
    client.post(
        "/api/skills/text/word-frequency/comments", json={"body": "on word-frequency"},
        headers={"Authorization": f"Bearer {token}"},
    )

    pivot_comments = client.get(
        "/api/skills/excel/pivot-analysis/comments", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert [c["body"] for c in pivot_comments] == ["on pivot"]
