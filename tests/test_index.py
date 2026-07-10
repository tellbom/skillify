"""Tests for T2.2 — the skill index table (models/db/ingest/queries), run against SQLite."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.ingest import ReleaseEvent, upsert_release
from skillify.index.queries import get_versions, list_latest, search


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


def test_upsert_then_query(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event())

    with session_scope(engine) as session:
        versions = get_versions(session, "excel", "pivot-analysis")
        assert len(versions) == 1
        assert versions[0].version == "0.1.0"
        assert versions[0].tags == ["excel", "data"]


def test_upsert_falls_back_to_update_on_conflicting_insert(engine) -> None:
    """M-G (docs/review-m2-m6.md): simulates the race two concurrent writers hit — a row
    for this identity already exists by the time `upsert_release` attempts its insert
    (previously this surfaced as an unhandled IntegrityError on commit instead of updating
    the winner's row)."""
    from skillify.index.models import SkillIndexEntry

    with session_scope(engine) as session:
        session.add(
            SkillIndexEntry(
                namespace="excel", name="pivot-analysis", version="0.1.0",
                description="won the race", author="Other Writer", tags=[], checksum="c" * 64,
                release_url="http://forgejo.local/x", published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        session.flush()  # lands in the outer (non-nested) transaction, ahead of the SAVEPOINT below
        # Same session, no intervening commit — the insert below must go through the
        # SAVEPOINT/IntegrityError fallback path, not the plain select-then-branch.
        upsert_release(session, _event(description="lost the race, should become an update"))

    with session_scope(engine) as session:
        versions = get_versions(session, "excel", "pivot-analysis")
        assert len(versions) == 1
        assert versions[0].description == "lost the race, should become an update"


def test_upsert_is_idempotent_for_same_version(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event(description="v1 desc"))
    with session_scope(engine) as session:
        upsert_release(session, _event(description="v1 desc, corrected"))

    with session_scope(engine) as session:
        versions = get_versions(session, "excel", "pivot-analysis")
        assert len(versions) == 1
        assert versions[0].description == "v1 desc, corrected"


def test_multiple_versions_are_separate_rows(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event(version="0.1.0"))
        upsert_release(session, _event(version="0.2.0"))

    with session_scope(engine) as session:
        versions = get_versions(session, "excel", "pivot-analysis")
        assert {v.version for v in versions} == {"0.1.0", "0.2.0"}


def test_list_latest_picks_most_recently_published_per_skill(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event(version="0.1.0", published_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        upsert_release(session, _event(version="0.2.0", published_at=datetime(2026, 2, 1, tzinfo=timezone.utc)))
        upsert_release(
            session,
            _event(
                namespace="text", name="word-frequency", version="1.0.0",
                published_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
            ),
        )

    with session_scope(engine) as session:
        latest = list_latest(session)
        by_key = {(e.namespace, e.name): e.version for e in latest}
        assert by_key == {("excel", "pivot-analysis"): "0.2.0", ("text", "word-frequency"): "1.0.0"}


def test_search_matches_name_and_description(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event())
        upsert_release(
            session,
            _event(namespace="text", name="word-frequency", description="Count word frequency in text."),
        )

    with session_scope(engine) as session:
        assert {e.name for e in search(session, "pivot")} == {"pivot-analysis"}
        assert {e.name for e in search(session, "frequency")} == {"word-frequency"}
        assert search(session, "nonexistent") == []
