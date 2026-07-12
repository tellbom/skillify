"""C-2 — visibility into web-upload publish attempts (`skill_publish_jobs`).

`formal_publish.py::publish_workspace` records one row per (namespace, name, version) publish
attempt here, so a user can see (and be prompted to retry) their own failed uploads without
Skillify having to scan every Forgejo repo across every namespace for stranded draft
releases (see `publisher.py`'s A-2 draft-resume mechanism for why a stranded draft can exist
at all).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from skillify.index.models import SkillPublishJob


def record_job_result(
    session: Session,
    *,
    namespace: str,
    name: str,
    version: str,
    initiator: str,
    status: str,
    error_message: str | None,
    at: datetime,
) -> SkillPublishJob:
    """Idempotent + concurrency-safe insert-or-update on
    (namespace, name, version, initiator), using the same SAVEPOINT fallback pattern as
    `ingest.py::upsert_release`. A retry updates only that initiator's existing row."""
    if status not in ("succeeded", "failed"):
        raise ValueError(f"unknown status {status!r} (expected 'succeeded' or 'failed')")

    job = SkillPublishJob(
        namespace=namespace,
        name=name,
        version=version,
        initiator=initiator,
        status=status,
        error_message=error_message,
        created_at=at,
        updated_at=at,
    )
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
        return job
    except IntegrityError:
        pass

    existing = session.execute(
        select(SkillPublishJob).where(
            SkillPublishJob.namespace == namespace,
            SkillPublishJob.name == name,
            SkillPublishJob.version == version,
            SkillPublishJob.initiator == initiator,
        )
    ).scalar_one()
    existing.status = status
    existing.error_message = error_message
    existing.updated_at = at
    return existing


def list_my_failed_jobs(session: Session, initiator: str) -> list[SkillPublishJob]:
    """Failed publish attempts triggered by `initiator`, newest-updated first."""
    stmt = (
        select(SkillPublishJob)
        .where(SkillPublishJob.initiator == initiator, SkillPublishJob.status == "failed")
        .order_by(SkillPublishJob.updated_at.desc())
    )
    return list(session.execute(stmt).scalars())


def list_my_jobs(session: Session, initiator: str) -> list[SkillPublishJob]:
    """All publish attempts (any status) triggered by `initiator`, newest-updated first —
    for a "my publish results" view that isn't limited to just failures."""
    stmt = (
        select(SkillPublishJob)
        .where(SkillPublishJob.initiator == initiator)
        .order_by(SkillPublishJob.updated_at.desc())
    )
    return list(session.execute(stmt).scalars())
