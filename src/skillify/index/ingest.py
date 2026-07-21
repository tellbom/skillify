"""Write path: a successful publish (T1.3/T2.1) upserts one index row (T2.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from skillify.index.models import SkillIndexEntry


@dataclass
class ReleaseEvent:
    namespace: str
    name: str
    version: str
    description: str
    author: str
    tags: list[str]
    checksum: str
    release_url: str
    published_at: datetime
    orchestration: dict = field(default_factory=dict)
    governance: dict = field(default_factory=dict)


def upsert_release(session: Session, event: ReleaseEvent) -> SkillIndexEntry:
    """Idempotent + concurrency-safe: re-ingesting the same (namespace, name, version)
    updates the existing row in place rather than raising a unique-constraint error (a
    webhook redelivery should be safe to re-process, per PLAN.md §6.5's re-delivery/
    idempotency posture).

    M-G (docs/review-m2-m6.md): the previous select-then-branch was a check-then-act race —
    two concurrent redeliveries (or a webhook publish racing a `skillctl publish`) could
    both see no existing row and both attempt an insert, and the loser would raise
    `IntegrityError` on the caller's commit instead of updating. This now attempts the
    insert inside a SAVEPOINT first; on a unique-constraint violation (another writer won
    the race) it falls back to updating that writer's row instead."""
    entry = SkillIndexEntry(
        namespace=event.namespace,
        name=event.name,
        version=event.version,
        description=event.description,
        author=event.author,
        tags=event.tags,
        checksum=event.checksum,
        release_url=event.release_url,
        published_at=event.published_at,
        orchestration=event.orchestration,
        governance=event.governance,
    )
    try:
        with session.begin_nested():
            session.add(entry)
            session.flush()
        return entry
    except IntegrityError:
        pass

    existing = session.execute(
        select(SkillIndexEntry).where(
            SkillIndexEntry.namespace == event.namespace,
            SkillIndexEntry.name == event.name,
            SkillIndexEntry.version == event.version,
        )
    ).scalar_one()
    existing.description = event.description
    existing.author = event.author
    existing.tags = event.tags
    existing.checksum = event.checksum
    existing.release_url = event.release_url
    existing.published_at = event.published_at
    existing.orchestration = event.orchestration
    existing.governance = event.governance
    return existing
