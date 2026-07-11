"""Tests for C-6 leaderboard time-window dimension: `queries.leaderboard(window=...)` and
`events.install_counts(since=...)`. The cutoff is computed in Python
(`datetime.now(timezone.utc) - timedelta(days=7|30)`) and bound as a plain parameter in
`WHERE occurred_at >= :cutoff` — no DB-side date/time function involved, so these tests only
need to prove the Python-side boundary logic is correct; the SQL comparison itself is a
portable `>=` on a datetime column."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.events import install_counts, record_event
from skillify.index.ingest import ReleaseEvent, upsert_release
from skillify.index.queries import leaderboard


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
        author="jane",
        tags=["excel", "data"],
        checksum="a" * 64,
        release_url="http://forgejo.local/excel/pivot-analysis/releases/tag/v0.1.0",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return ReleaseEvent(**defaults)


# --- events.py: install_counts(since=...) ----------------------------------------------


def test_install_counts_without_since_counts_everything(engine) -> None:
    now = datetime.now(timezone.utc)
    with session_scope(engine) as session:
        record_event(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            event_type="install", occurred_at=now - timedelta(days=100),
        )
        record_event(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            event_type="install", occurred_at=now - timedelta(days=1),
        )

    with session_scope(engine) as session:
        counts = install_counts(session)
        assert counts[("excel", "pivot-analysis")] == 2


def test_install_counts_since_excludes_older_events(engine) -> None:
    now = datetime.now(timezone.utc)
    with session_scope(engine) as session:
        record_event(  # 10 days ago -> outside a 7-day window
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            event_type="install", occurred_at=now - timedelta(days=10),
        )
        record_event(  # 1 day ago -> inside a 7-day window
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            event_type="install", occurred_at=now - timedelta(days=1),
        )

    with session_scope(engine) as session:
        cutoff = now - timedelta(days=7)
        counts = install_counts(session, since=cutoff)
        assert counts[("excel", "pivot-analysis")] == 1


# --- queries.py: leaderboard(window=...) -----------------------------------------------


def test_leaderboard_rejects_bad_window(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event())
        with pytest.raises(ValueError):
            leaderboard(session, "installs", window="bogus")


def test_leaderboard_installs_week_window_excludes_older_installs(engine) -> None:
    now = datetime.now(timezone.utc)
    with session_scope(engine) as session:
        upsert_release(session, _event(name="pivot-analysis"))
        upsert_release(session, _event(name="word-frequency"))

        # pivot-analysis: 3 installs, all 20 days ago (outside week AND month... wait, month is 30d)
        for _ in range(3):
            record_event(
                session, namespace="excel", name="pivot-analysis", version="0.1.0",
                event_type="install", occurred_at=now - timedelta(days=20),
            )
        # word-frequency: 1 install, 2 days ago (inside week window)
        record_event(
            session, namespace="excel", name="word-frequency", version="0.1.0",
            event_type="install", occurred_at=now - timedelta(days=2),
        )

    with session_scope(engine) as session:
        rows = leaderboard(session, "installs", window="all")
        assert rows[0].entry.name == "pivot-analysis"
        assert rows[0].install_count == 3
        assert rows[1].install_count == 1

        rows_week = leaderboard(session, "installs", window="week")
        by_name = {r.entry.name: r.install_count for r in rows_week}
        assert by_name["pivot-analysis"] == 0  # 20 days ago -> outside 7-day window
        assert by_name["word-frequency"] == 1  # 2 days ago -> inside 7-day window
        assert rows_week[0].entry.name == "word-frequency"  # now ranks first under "week"

        rows_month = leaderboard(session, "installs", window="month")
        by_name_month = {r.entry.name: r.install_count for r in rows_month}
        assert by_name_month["pivot-analysis"] == 3  # 20 days ago -> inside 30-day window
        assert by_name_month["word-frequency"] == 1


def test_leaderboard_installs_month_boundary(engine) -> None:
    """An event exactly on/just past the 30-day cutoff should behave per `>=` semantics."""
    now = datetime.now(timezone.utc)
    with session_scope(engine) as session:
        upsert_release(session, _event(name="pivot-analysis"))
        record_event(  # 31 days ago -> outside month window
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            event_type="install", occurred_at=now - timedelta(days=31),
        )

    with session_scope(engine) as session:
        rows = leaderboard(session, "installs", window="month")
        assert rows[0].install_count == 0


def test_leaderboard_window_ignored_for_rating_and_recent_dimensions(engine) -> None:
    """Per the brief: `rating`/`recent` don't get a time-window concept — passing a window
    other than "all" must not raise and must not change their ordering/values."""
    with session_scope(engine) as session:
        upsert_release(session, _event(name="pivot-analysis", published_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        upsert_release(session, _event(name="word-frequency", published_at=datetime(2026, 1, 5, tzinfo=timezone.utc)))

    with session_scope(engine) as session:
        recent_all = leaderboard(session, "recent", window="all")
        recent_week = leaderboard(session, "recent", window="week")
        assert [r.entry.name for r in recent_all] == [r.entry.name for r in recent_week]

        rating_all = leaderboard(session, "rating", window="all")
        rating_month = leaderboard(session, "rating", window="month")
        assert [r.entry.name for r in rating_all] == [r.entry.name for r in rating_month]
