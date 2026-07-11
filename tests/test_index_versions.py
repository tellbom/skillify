"""Tests for C-1 version center: yanked filtering in queries.py + yank.py (SQLite)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.ingest import ReleaseEvent, upsert_release
from skillify.index.models import SkillNamespaceOwner
from skillify.index.queries import get_versions, leaderboard, list_latest, search
from skillify.index.yank import VersionNotFoundError, can_manage_version, set_yanked


@pytest.fixture()
def engine():
    eng = make_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def _event(**overrides) -> ReleaseEvent:
    defaults = dict(
        namespace="excel",
        name="pivot-analysis",
        version="0.1.0",
        description="Build pivot tables from tabular data.",
        author="Jane Doe",
        tags=["excel", "data"],
        checksum="a" * 64,
        release_url="http://forgejo.local/excel/pivot-analysis/releases/tag/v0.1.0",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return ReleaseEvent(**defaults)


def test_new_entries_default_to_not_yanked(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event())
    with session_scope(engine) as session:
        versions = get_versions(session, "excel", "pivot-analysis")
        assert versions[0].yanked is False


def test_yank_excludes_from_list_latest_search_leaderboard_but_not_get_versions(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event(version="0.1.0", published_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        upsert_release(session, _event(version="0.2.0", published_at=datetime(2026, 2, 1, tzinfo=timezone.utc)))

    with session_scope(engine) as session:
        set_yanked(session, namespace="excel", name="pivot-analysis", version="0.2.0", yanked=True)

    with session_scope(engine) as session:
        # get_versions still sees everything, flagged.
        versions = {v.version: v.yanked for v in get_versions(session, "excel", "pivot-analysis")}
        assert versions == {"0.1.0": False, "0.2.0": True}

        # list_latest falls back to the newest non-yanked version.
        latest = list_latest(session)
        assert len(latest) == 1
        assert latest[0].version == "0.1.0"

        # search/leaderboard propagate the same default exclusion.
        results, total = search(session, "pivot")
        assert {e.version for e in results} == {"0.1.0"}
        assert total == 1
        rows = leaderboard(session, "recent")
        assert [r.entry.version for r in rows] == ["0.1.0"]

        # include_yanked=True restores the old unfiltered behavior.
        latest_all = list_latest(session, include_yanked=True)
        assert {e.version for e in latest_all} == {"0.2.0"}  # 0.2.0 is still the newest overall


def test_yank_only_version_removes_skill_from_list_latest(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event(version="0.1.0"))

    with session_scope(engine) as session:
        set_yanked(session, namespace="excel", name="pivot-analysis", version="0.1.0", yanked=True)

    with session_scope(engine) as session:
        assert list_latest(session) == []
        results, total = search(session, "pivot")
        assert results == []
        assert total == 0
        assert leaderboard(session, "recent") == []
        # get_versions still shows it, yanked.
        versions = get_versions(session, "excel", "pivot-analysis")
        assert len(versions) == 1
        assert versions[0].yanked is True


def test_unyank_restores_visibility(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event(version="0.1.0"))
    with session_scope(engine) as session:
        set_yanked(session, namespace="excel", name="pivot-analysis", version="0.1.0", yanked=True)
    with session_scope(engine) as session:
        assert list_latest(session) == []

    with session_scope(engine) as session:
        entry = set_yanked(session, namespace="excel", name="pivot-analysis", version="0.1.0", yanked=False)
        assert entry.yanked is False

    with session_scope(engine) as session:
        latest = list_latest(session)
        assert len(latest) == 1
        assert latest[0].version == "0.1.0"
        assert latest[0].yanked is False


def test_set_yanked_raises_for_unknown_version(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event(version="0.1.0"))

    with session_scope(engine) as session:
        with pytest.raises(VersionNotFoundError):
            set_yanked(session, namespace="excel", name="pivot-analysis", version="9.9.9", yanked=True)


def test_can_manage_version_checks_namespace_owner(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event())
        session.add(
            SkillNamespaceOwner(
                namespace="excel", owner_username="owner-bob", claimed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
            )
        )

    with session_scope(engine) as session:
        assert can_manage_version(session, namespace="excel", username="owner-bob") is True
        assert can_manage_version(session, namespace="excel", username="someone-else") is False
        # No owner row at all for a namespace that's never been claimed.
        assert can_manage_version(session, namespace="text", username="anyone") is False
