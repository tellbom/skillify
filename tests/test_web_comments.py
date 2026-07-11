"""Tests for T5.1 — skill comments; C-5 extends with replies (parentId) and soft-delete.

M-A (docs/review-m2-m6.md): reads now require a Keycloak session too, not just writes
(the market-wide login requirement) — this superseded the original "public read" design.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.models import SkillNamespaceOwner
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


def test_reply_to_comment(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    headers = {"Authorization": f"Bearer {token}"}

    top = client.post(
        "/api/skills/excel/pivot-analysis/comments", json={"body": "top level"}, headers=headers
    ).json()
    assert top["parentId"] is None

    reply = client.post(
        "/api/skills/excel/pivot-analysis/comments",
        json={"body": "a reply", "parentId": top["id"]},
        headers=headers,
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["parentId"] == top["id"]

    comments = client.get("/api/skills/excel/pivot-analysis/comments", headers=headers).json()
    assert len(comments) == 2
    assert all(c["deleted"] is False for c in comments)


def test_reply_to_parent_in_other_skill_rejected(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    headers = {"Authorization": f"Bearer {token}"}

    top = client.post(
        "/api/skills/excel/pivot-analysis/comments", json={"body": "top level"}, headers=headers
    ).json()

    resp = client.post(
        "/api/skills/text/word-frequency/comments",
        json={"body": "wrong parent", "parentId": top["id"]},
        headers=headers,
    )
    assert resp.status_code == 400


def test_delete_comment_requires_auth(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    resp = client.delete("/api/skills/excel/pivot-analysis/comments/1")
    assert resp.status_code == 401


def test_author_can_soft_delete_own_comment(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    headers = {"Authorization": f"Bearer {token}"}

    comment = client.post(
        "/api/skills/excel/pivot-analysis/comments", json={"body": "delete me"}, headers=headers
    ).json()

    del_resp = client.delete(f"/api/skills/excel/pivot-analysis/comments/{comment['id']}", headers=headers)
    assert del_resp.status_code == 204

    comments = client.get("/api/skills/excel/pivot-analysis/comments", headers=headers).json()
    assert comments[0]["deleted"] is True
    assert comments[0]["body"] == "[已删除]"
    assert comments[0]["id"] == comment["id"]  # tree-relevant fields preserved


def test_non_author_non_owner_cannot_delete_comment(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    author_token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    stranger_token = fake_keycloak.mint_token(audience="skillify-web", subject="mallory")

    comment = client.post(
        "/api/skills/excel/pivot-analysis/comments",
        json={"body": "mine"},
        headers={"Authorization": f"Bearer {author_token}"},
    ).json()

    resp = client.delete(
        f"/api/skills/excel/pivot-analysis/comments/{comment['id']}",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert resp.status_code == 403

    comments = client.get(
        "/api/skills/excel/pivot-analysis/comments", headers={"Authorization": f"Bearer {author_token}"}
    ).json()
    assert comments[0]["deleted"] is False
    assert comments[0]["body"] == "mine"


def test_namespace_owner_can_delete_others_comment(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    index_db_url = _configure(monkeypatch, tmp_path, fake_keycloak)
    author_token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    owner_token = fake_keycloak.mint_token(audience="skillify-web", subject="ns-owner")

    comment = client.post(
        "/api/skills/excel/pivot-analysis/comments",
        json={"body": "someone else's skill"},
        headers={"Authorization": f"Bearer {author_token}"},
    ).json()

    engine = make_engine(index_db_url)
    with session_scope(engine) as session:
        session.add(
            SkillNamespaceOwner(
                namespace="excel", owner_username="ns-owner", claimed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
            )
        )

    resp = client.delete(
        f"/api/skills/excel/pivot-analysis/comments/{comment['id']}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 204


def test_delete_unknown_comment_is_404(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    resp = client.delete(
        "/api/skills/excel/pivot-analysis/comments/999", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404

