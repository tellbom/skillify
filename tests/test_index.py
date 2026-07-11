"""Tests for T2.2 — the skill index table (models/db/ingest/queries), run against SQLite."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.events import record_event
from skillify.index.ingest import ReleaseEvent, upsert_release
from skillify.index.queries import get_versions, list_latest, search
from skillify.index.ratings import upsert_rating
from skillify.index.yank import set_yanked


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
        # C-4: search() now returns (page_of_results, total_matching_count).
        results, total = search(session, "pivot")
        assert {e.name for e in results} == {"pivot-analysis"}
        assert total == 1

        results, total = search(session, "frequency")
        assert {e.name for e in results} == {"word-frequency"}
        assert total == 1

        results, total = search(session, "nonexistent")
        assert results == []
        assert total == 0


# --- C-4: SQL-pushed-down search() — pagination/filter/sort/tags-degradation/yanked ---


def _seed_five_skills(session) -> None:
    """Five distinct (namespace, name) skills, each with one published version, spread
    across two namespaces/authors so namespace/author filtering has something to narrow."""
    for i in range(5):
        upsert_release(
            session,
            _event(
                namespace="excel" if i % 2 == 0 else "text",
                name=f"skill-{i}",
                author="Jane Doe" if i % 2 == 0 else "Bob Lee",
                description=f"Skill number {i}.",
                tags=["excel", "data"] if i % 2 == 0 else ["text"],
                published_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
            ),
        )


def test_search_paginates_in_sql(engine) -> None:
    with session_scope(engine) as session:
        _seed_five_skills(session)

    with session_scope(engine) as session:
        page1, total = search(session, None, sort="updated", page=1, page_size=2)
        page2, total2 = search(session, None, sort="updated", page=2, page_size=2)
        page3, total3 = search(session, None, sort="updated", page=3, page_size=2)

        assert total == total2 == total3 == 5
        assert [e.name for e in page1] == ["skill-4", "skill-3"]  # updated desc: newest first
        assert [e.name for e in page2] == ["skill-2", "skill-1"]
        assert [e.name for e in page3] == ["skill-0"]


def test_search_filters_by_namespace_and_author(engine) -> None:
    with session_scope(engine) as session:
        _seed_five_skills(session)

    with session_scope(engine) as session:
        results, total = search(session, None, namespace="excel", page_size=10)
        assert total == 3
        assert {e.namespace for e in results} == {"excel"}

        results, total = search(session, None, author="Bob Lee", page_size=10)
        assert total == 2
        assert {e.author for e in results} == {"Bob Lee"}

        results, total = search(session, None, namespace="text", author="Bob Lee", page_size=10)
        assert total == 2

        results, total = search(session, None, namespace="excel", author="Bob Lee", page_size=10)
        assert total == 0
        assert results == []


def test_search_query_is_case_insensitive_and_matches_name_or_description(engine) -> None:
    with session_scope(engine) as session:
        _seed_five_skills(session)

    with session_scope(engine) as session:
        results, total = search(session, "SKILL-2", page_size=10)
        assert total == 1
        assert results[0].name == "skill-2"

        results, total = search(session, "NUMBER 3", page_size=10)
        assert total == 1
        assert results[0].name == "skill-3"


def test_search_tags_filter_degrades_to_application_layer_pagination(engine) -> None:
    """Tags filtering can't be pushed to SQL (JSON-function dialect risk across
    SQLite/Postgres/DM8 — see search()'s docstring), so this exercises the documented
    degraded path: SQL narrows everything else, tags + pagination both happen in Python."""
    with session_scope(engine) as session:
        _seed_five_skills(session)

    with session_scope(engine) as session:
        # Only the odd-indexed skills (text namespace) have the "text" tag.
        results, total = search(session, None, tags=["text"], page_size=10)
        assert total == 2
        assert {e.name for e in results} == {"skill-1", "skill-3"}

        # Tags degradation still composes with SQL-level namespace filtering.
        results, total = search(session, None, namespace="excel", tags=["data"], page_size=10)
        assert total == 3
        assert {e.name for e in results} == {"skill-0", "skill-2", "skill-4"}

        # A tag nothing has yields an empty page with total 0, not an error.
        results, total = search(session, None, tags=["nonexistent-tag"], page_size=10)
        assert results == []
        assert total == 0

        # Manual pagination within the degraded path still slices correctly.
        page1, total = search(session, None, tags=["excel"], page=1, page_size=2)
        page2, total2 = search(session, None, tags=["excel"], page=2, page_size=2)
        assert total == total2 == 3
        assert len(page1) == 2
        assert len(page2) == 1
        assert {e.name for e in page1} | {e.name for e in page2} == {"skill-0", "skill-2", "skill-4"}


def test_search_sort_updated_orders_by_published_at_desc(engine) -> None:
    with session_scope(engine) as session:
        _seed_five_skills(session)

    with session_scope(engine) as session:
        results, _ = search(session, None, sort="updated", page_size=10)
        assert [e.name for e in results] == ["skill-4", "skill-3", "skill-2", "skill-1", "skill-0"]


def test_search_sort_installs_orders_by_sql_aggregated_install_count(engine) -> None:
    with session_scope(engine) as session:
        _seed_five_skills(session)

    with session_scope(engine) as session:
        # skill-2 gets 3 installs, skill-0 gets 1, the rest get 0.
        for _ in range(3):
            record_event(
                session, namespace="excel", name="skill-2", version="0.1.0", event_type="install",
                occurred_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )
        record_event(
            session, namespace="excel", name="skill-0", version="0.1.0", event_type="install",
            occurred_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

    with session_scope(engine) as session:
        results, total = search(session, None, sort="installs", page_size=10)
        assert total == 5
        names_in_order = [e.name for e in results]
        # skill-2 (3 installs) first, skill-0 (1 install) second; the zero-install skills
        # follow in some stable order (namespace, name tiebreaker) after them.
        assert names_in_order[0] == "skill-2"
        assert names_in_order[1] == "skill-0"
        assert set(names_in_order[2:]) == {"skill-1", "skill-3", "skill-4"}


def test_search_sort_rating_orders_by_sql_aggregated_average_nulls_last(engine) -> None:
    with session_scope(engine) as session:
        _seed_five_skills(session)

    with session_scope(engine) as session:
        # skill-0 -> avg 5.0 (one rating), skill-2 -> avg 3.0 (two ratings averaged),
        # skill-4 stays unrated (must sort after any rated skill regardless of "0 vs None").
        upsert_rating(
            session, namespace="excel", name="skill-0", author="rater-a", score=5,
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        upsert_rating(
            session, namespace="excel", name="skill-2", author="rater-a", score=2,
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        upsert_rating(
            session, namespace="excel", name="skill-2", author="rater-b", score=4,
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

    with session_scope(engine) as session:
        results, total = search(session, None, sort="rating", page_size=10)
        assert total == 5
        names_in_order = [e.name for e in results]
        assert names_in_order[0] == "skill-0"  # avg 5.0
        assert names_in_order[1] == "skill-2"  # avg 3.0
        # Unrated skills (skill-1, skill-3, skill-4) come last, in some stable order.
        assert set(names_in_order[2:]) == {"skill-1", "skill-3", "skill-4"}


def test_search_excludes_yanked_versions_by_default(engine) -> None:
    with session_scope(engine) as session:
        _seed_five_skills(session)

    with session_scope(engine) as session:
        set_yanked(session, namespace="excel", name="skill-0", version="0.1.0", yanked=True)

    with session_scope(engine) as session:
        results, total = search(session, None, page_size=10)
        assert total == 4
        assert "skill-0" not in {e.name for e in results}

        results, total = search(session, None, include_yanked=True, page_size=10)
        assert total == 5
        assert "skill-0" in {e.name for e in results}


def test_search_rejects_unknown_sort_and_invalid_page_params(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event())

    with session_scope(engine) as session:
        with pytest.raises(ValueError):
            search(session, None, sort="bogus")
        with pytest.raises(ValueError):
            search(session, None, page=0)
        with pytest.raises(ValueError):
            search(session, None, page_size=0)
