"""Tests for T5.2 — leaderboard (installs/rating/recency), ratings, and the shared
install/run event-reporting endpoint (also used by T6.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.events import record_event
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
                description="Build pivot tables.", author="Jane Doe", tags=["excel"],
                checksum="a" * 64, release_url="http://forgejo.local/x",
                published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        )
        upsert_release(
            session,
            ReleaseEvent(
                namespace="text", name="word-frequency", version="1.0.0",
                description="Count words.", author="Skillify examples", tags=["text"],
                checksum="b" * 64, release_url="http://forgejo.local/y",
                published_at=datetime(2026, 1, 5, tzinfo=timezone.utc),  # more recent
            ),
        )
    return url


def _configure(monkeypatch, tmp_path: Path, index_db_url: str, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")


def test_leaderboard_requires_auth(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.get("/api/leaderboard", params={"dimension": "recent"})
    assert resp.status_code == 401


def test_leaderboard_recent_dimension(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.get(
        "/api/leaderboard",
        params={"dimension": "recent"},
        headers={"Authorization": f"Bearer {fake_keycloak.mint_token(audience='skillify-web')}"},
    )
    assert resp.status_code == 200
    names = [r["name"] for r in resp.json()]
    assert names == ["word-frequency", "pivot-analysis"]  # word-frequency published later


def test_leaderboard_rejects_bad_dimension(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.get(
        "/api/leaderboard",
        params={"dimension": "bogus"},
        headers={"Authorization": f"Bearer {fake_keycloak.mint_token(audience='skillify-web')}"},
    )
    assert resp.status_code == 400


def test_leaderboard_installs_dimension_reflects_events(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)

    for _ in range(3):
        r = client.post(
            "/api/skills/excel/pivot-analysis/events",
            json={"eventType": "install", "version": "0.1.0"},
        )
        assert r.status_code == 204
    client.post("/api/skills/text/word-frequency/events", json={"eventType": "install", "version": "1.0.0"})

    resp = client.get(
        "/api/leaderboard",
        params={"dimension": "installs"},
        headers={"Authorization": f"Bearer {fake_keycloak.mint_token(audience='skillify-web')}"},
    )
    rows = resp.json()
    assert rows[0]["name"] == "pivot-analysis"
    assert rows[0]["installCount"] == 3
    assert rows[1]["installCount"] == 1


def test_leaderboard_window_filters_installs(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    """C-6: `window` query param reaches `leaderboard(..., window=...)` and restricts the
    "installs" dimension's counts — old events (well outside a 7-day window) don't count
    toward the "week" total."""
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)

    with session_scope(make_engine(index_db_url)) as session:
        record_event(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            event_type="install", occurred_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )

    resp_all = client.get(
        "/api/leaderboard",
        params={"dimension": "installs", "window": "all"},
        headers={"Authorization": f"Bearer {fake_keycloak.mint_token(audience='skillify-web')}"},
    )
    rows_all = {r["name"]: r["installCount"] for r in resp_all.json()}
    assert rows_all["pivot-analysis"] == 1

    resp_week = client.get(
        "/api/leaderboard",
        params={"dimension": "installs", "window": "week"},
        headers={"Authorization": f"Bearer {fake_keycloak.mint_token(audience='skillify-web')}"},
    )
    rows_week = {r["name"]: r["installCount"] for r in resp_week.json()}
    assert rows_week["pivot-analysis"] == 0  # 2020 event is far outside any 7-day window


def test_leaderboard_rejects_bad_window(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.get(
        "/api/leaderboard",
        params={"dimension": "installs", "window": "bogus"},
        headers={"Authorization": f"Bearer {fake_keycloak.mint_token(audience='skillify-web')}"},
    )
    assert resp.status_code == 400


def test_rating_requires_auth(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.post("/api/skills/excel/pivot-analysis/rating", json={"score": 5})
    assert resp.status_code == 401


def test_rating_upsert_and_leaderboard_rating_dimension(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    jane = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    bob = fake_keycloak.mint_token(audience="skillify-web", subject="bob")

    r1 = client.post(
        "/api/skills/excel/pivot-analysis/rating", json={"score": 4},
        headers={"Authorization": f"Bearer {jane}"},
    )
    assert r1.status_code == 200
    assert r1.json()["ratingAverage"] == 4.0
    assert r1.json()["ratingCount"] == 1

    client.post(
        "/api/skills/excel/pivot-analysis/rating", json={"score": 2},
        headers={"Authorization": f"Bearer {bob}"},
    )
    # jane re-rates -> upsert, not a third row
    r3 = client.post(
        "/api/skills/excel/pivot-analysis/rating", json={"score": 5},
        headers={"Authorization": f"Bearer {jane}"},
    )
    assert r3.json()["ratingCount"] == 2
    assert r3.json()["ratingAverage"] == 3.5  # (5 + 2) / 2

    resp = client.get(
        "/api/leaderboard",
        params={"dimension": "rating"},
        headers={"Authorization": f"Bearer {jane}"},
    )
    rows = resp.json()
    assert rows[0]["name"] == "pivot-analysis"
    assert rows[0]["ratingAverage"] == 3.5


def test_rating_out_of_range_rejected(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")
    resp = client.post(
        "/api/skills/excel/pivot-analysis/rating", json={"score": 9},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_event_reporting_accepts_run_events(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.post(
        "/api/skills/excel/pivot-analysis/events",
        json={"eventType": "run", "version": "0.1.0", "success": True, "machineId": "abc123"},
    )
    assert resp.status_code == 204


def test_event_reporting_rejects_unknown_type(tmp_path: Path, monkeypatch, index_db_url, fake_keycloak) -> None:
    _configure(monkeypatch, tmp_path, index_db_url, fake_keycloak)
    resp = client.post(
        "/api/skills/excel/pivot-analysis/events", json={"eventType": "bogus", "version": "0.1.0"}
    )
    assert resp.status_code == 400
