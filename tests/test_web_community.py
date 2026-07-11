"""Tests for C-5 web endpoints: star / subscription / my-subscriptions.

Follows tests/test_web_versions.py's fixture pattern (SQLite index DB + fake Keycloak).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.ingest import ReleaseEvent, upsert_release
from skillify.web.app import app
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
                description="Count word frequencies.", author="Bob",
                tags=["text"], checksum="b" * 64,
                release_url="http://forgejo.local/text/word-frequency/releases/tag/v1.0.0",
                published_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            ),
        )
    return url


def _configure(monkeypatch, tmp_path: Path, index_db_url: str, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")


def _auth_headers(fake_keycloak, subject: str = "jane") -> dict[str, str]:
    token = fake_keycloak.mint_token(audience="skillify-web", subject=subject)
    return {"Authorization": f"Bearer {token}"}


# --- star --------------------------------------------------------------------


def test_star_requires_auth(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.post("/api/skills/excel/pivot-analysis/star")
    assert resp.status_code == 401


def test_star_and_unstar(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    headers = _auth_headers(fake_keycloak, subject="jane")

    resp = client.post("/api/skills/excel/pivot-analysis/star", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"starred": True, "starCount": 1}

    # idempotent re-star
    resp = client.post("/api/skills/excel/pivot-analysis/star", headers=headers)
    assert resp.json() == {"starred": True, "starCount": 1}

    resp = client.delete("/api/skills/excel/pivot-analysis/star", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"starred": False, "starCount": 0}

    # idempotent un-star (already removed)
    resp = client.delete("/api/skills/excel/pivot-analysis/star", headers=headers)
    assert resp.json() == {"starred": False, "starCount": 0}


def test_star_count_aggregates_across_users(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    client.post("/api/skills/excel/pivot-analysis/star", headers=_auth_headers(fake_keycloak, subject="jane"))
    resp = client.post("/api/skills/excel/pivot-analysis/star", headers=_auth_headers(fake_keycloak, subject="bob"))
    assert resp.json() == {"starred": True, "starCount": 2}


# --- subscription --------------------------------------------------------------


def test_subscription_requires_auth(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.post("/api/skills/excel/pivot-analysis/subscription")
    assert resp.status_code == 401


def test_subscribe_and_unsubscribe(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    headers = _auth_headers(fake_keycloak, subject="jane")

    resp = client.post("/api/skills/excel/pivot-analysis/subscription", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"subscribed": True}

    resp = client.post("/api/skills/excel/pivot-analysis/subscription", headers=headers)
    assert resp.json() == {"subscribed": True}  # idempotent

    resp = client.delete("/api/skills/excel/pivot-analysis/subscription", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"subscribed": False}

    resp = client.delete("/api/skills/excel/pivot-analysis/subscription", headers=headers)
    assert resp.json() == {"subscribed": False}  # idempotent


# --- /api/my/subscriptions ------------------------------------------------------


def test_my_subscriptions_requires_auth(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.get("/api/my/subscriptions")
    assert resp.status_code == 401


def test_my_subscriptions_snapshot(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    headers = _auth_headers(fake_keycloak, subject="jane")

    resp = client.get("/api/my/subscriptions", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []

    client.post("/api/skills/excel/pivot-analysis/subscription", headers=headers)
    client.post("/api/skills/text/word-frequency/subscription", headers=headers)

    resp = client.get("/api/my/subscriptions", headers=headers)
    assert resp.status_code == 200
    entries = {(e["namespace"], e["name"]): e for e in resp.json()}
    assert set(entries) == {("excel", "pivot-analysis"), ("text", "word-frequency")}
    assert entries[("excel", "pivot-analysis")]["latestVersion"] == "0.1.0"
    assert entries[("text", "word-frequency")]["latestVersion"] == "1.0.0"


def test_my_subscriptions_does_not_leak_other_users(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    client.post(
        "/api/skills/excel/pivot-analysis/subscription", headers=_auth_headers(fake_keycloak, subject="jane")
    )

    resp = client.get("/api/my/subscriptions", headers=_auth_headers(fake_keycloak, subject="bob"))
    assert resp.json() == []


def test_my_subscriptions_reflects_latest_version_bump(monkeypatch, tmp_path, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    headers = _auth_headers(fake_keycloak, subject="jane")
    client.post("/api/skills/excel/pivot-analysis/subscription", headers=headers)

    engine = make_engine(index_db_url)
    with session_scope(engine) as session:
        upsert_release(
            session,
            ReleaseEvent(
                namespace="excel", name="pivot-analysis", version="0.2.0",
                description="v2", author="Jane Doe", tags=["excel"], checksum="c" * 64,
                release_url="http://forgejo.local/excel/pivot-analysis/releases/tag/v0.2.0",
                published_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            ),
        )

    resp = client.get("/api/my/subscriptions", headers=headers)
    entries = {(e["namespace"], e["name"]): e for e in resp.json()}
    assert entries[("excel", "pivot-analysis")]["latestVersion"] == "0.2.0"
