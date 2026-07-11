"""Tests for C-2 index-layer aggregation: skill_publish_jobs upsert semantics
(publish_jobs.py) and My Skills/My Namespaces/usage-stats aggregation (my_skills.py)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.events import record_event
from skillify.index.ingest import ReleaseEvent, upsert_release
from skillify.index.models import SkillNamespaceOwner
from skillify.index.my_skills import list_my_namespaces, list_my_skills, my_usage_stats
from skillify.index.publish_jobs import list_my_failed_jobs, list_my_jobs, record_job_result


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


# --- publish_jobs.py: upsert semantics -------------------------------------------------


def test_record_job_result_inserts_new_row(engine) -> None:
    with session_scope(engine) as session:
        job = record_job_result(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            initiator="jane", status="failed", error_message="boom",
            at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert job.id is not None

    with session_scope(engine) as session:
        jobs = list_my_jobs(session, "jane")
        assert len(jobs) == 1
        assert jobs[0].status == "failed"
        assert jobs[0].error_message == "boom"


def test_record_job_result_retry_updates_same_row_not_insert(engine) -> None:
    """The whole point of UniqueConstraint(namespace, name, version): a retry of the same
    version updates the existing row's status/error_message/updated_at rather than
    accumulating a second row."""
    with session_scope(engine) as session:
        record_job_result(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            initiator="jane", status="failed", error_message="network error",
            at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    with session_scope(engine) as session:
        record_job_result(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            initiator="jane", status="succeeded", error_message=None,
            at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

    with session_scope(engine) as session:
        jobs = list_my_jobs(session, "jane")
        assert len(jobs) == 1  # still just one row
        assert jobs[0].status == "succeeded"
        assert jobs[0].error_message is None
        # SQLite round-trips datetimes as naive; compare the wall-clock value only (same
        # caveat as other index tests dealing with DateTime(timezone=True) on SQLite).
        assert jobs[0].updated_at.replace(tzinfo=timezone.utc) == datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_record_job_result_keeps_same_target_isolated_per_initiator(engine) -> None:
    with session_scope(engine) as session:
        record_job_result(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            initiator="jane", status="succeeded", error_message=None,
            at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    with session_scope(engine) as session:
        record_job_result(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            initiator="mallory", status="failed", error_message="namespace is owned by jane",
            at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

    with session_scope(engine) as session:
        jane_jobs = list_my_jobs(session, "jane")
        mallory_jobs = list_my_jobs(session, "mallory")
        assert len(jane_jobs) == 1
        assert jane_jobs[0].status == "succeeded"
        assert len(mallory_jobs) == 1
        assert mallory_jobs[0].status == "failed"


def test_list_my_failed_jobs_filters_status_and_initiator(engine) -> None:
    with session_scope(engine) as session:
        record_job_result(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            initiator="jane", status="failed", error_message="x",
            at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        record_job_result(
            session, namespace="excel", name="other-skill", version="0.1.0",
            initiator="jane", status="succeeded", error_message=None,
            at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        record_job_result(
            session, namespace="text", name="word-count", version="0.1.0",
            initiator="bob", status="failed", error_message="y",
            at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        )

    with session_scope(engine) as session:
        jane_failed = list_my_failed_jobs(session, "jane")
        assert [j.name for j in jane_failed] == ["pivot-analysis"]

        jane_all = list_my_jobs(session, "jane")
        assert {j.name for j in jane_all} == {"pivot-analysis", "other-skill"}

        bob_failed = list_my_failed_jobs(session, "bob")
        assert [j.name for j in bob_failed] == ["word-count"]


def test_list_my_jobs_orders_by_updated_at_desc(engine) -> None:
    with session_scope(engine) as session:
        record_job_result(
            session, namespace="excel", name="a", version="0.1.0",
            initiator="jane", status="failed", error_message="x",
            at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        record_job_result(
            session, namespace="excel", name="b", version="0.1.0",
            initiator="jane", status="failed", error_message="x",
            at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        )

    with session_scope(engine) as session:
        jobs = list_my_jobs(session, "jane")
        assert [j.name for j in jobs] == ["b", "a"]


def test_record_job_result_rejects_unknown_status(engine) -> None:
    with session_scope(engine) as session:
        with pytest.raises(ValueError):
            record_job_result(
                session, namespace="excel", name="pivot-analysis", version="0.1.0",
                initiator="jane", status="bogus", error_message=None,
                at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )


# --- my_skills.py: aggregation ----------------------------------------------------------


def test_list_my_skills_filters_by_author_and_uses_latest_version(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event(version="0.1.0", author="jane"))
        upsert_release(session, _event(version="0.2.0", author="jane", published_at=datetime(2026, 2, 1, tzinfo=timezone.utc)))
        upsert_release(session, _event(name="other-skill", author="bob"))

    with session_scope(engine) as session:
        mine = list_my_skills(session, "jane")
        assert len(mine) == 1
        assert mine[0].name == "pivot-analysis"
        assert mine[0].version == "0.2.0"  # latest, not first


def test_list_my_skills_empty_for_unknown_author(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event())

    with session_scope(engine) as session:
        assert list_my_skills(session, "nobody") == []


def test_list_my_namespaces_filters_by_owner(engine) -> None:
    with session_scope(engine) as session:
        session.add(
            SkillNamespaceOwner(namespace="excel", owner_username="jane", claimed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        )
        session.add(
            SkillNamespaceOwner(namespace="text", owner_username="bob", claimed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        )

    with session_scope(engine) as session:
        mine = list_my_namespaces(session, "jane")
        assert [n.namespace for n in mine] == ["excel"]
        assert list_my_namespaces(session, "nobody") == []


def test_my_usage_stats_sums_installs_across_my_skills(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event(version="0.1.0", author="jane"))
        upsert_release(session, _event(name="other-skill", author="jane"))
        upsert_release(session, _event(name="not-mine", author="bob"))

        record_event(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            event_type="install", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        record_event(
            session, namespace="excel", name="pivot-analysis", version="0.1.0",
            event_type="install", occurred_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        record_event(
            session, namespace="excel", name="other-skill", version="0.1.0",
            event_type="install", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        record_event(
            session, namespace="excel", name="not-mine", version="0.1.0",
            event_type="install", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    with session_scope(engine) as session:
        stats = my_usage_stats(session, "jane")
        assert stats["totalSkills"] == 2
        assert stats["totalInstalls"] == 3  # 2 + 1, excludes bob's "not-mine"
        assert stats["installsBySkill"] == {"excel/pivot-analysis": 2, "excel/other-skill": 1}


def test_my_usage_stats_empty_for_unknown_author(engine) -> None:
    with session_scope(engine) as session:
        upsert_release(session, _event())

    with session_scope(engine) as session:
        stats = my_usage_stats(session, "nobody")
        assert stats == {"totalSkills": 0, "totalInstalls": 0, "installsBySkill": {}}
