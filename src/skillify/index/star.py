"""Skill stars (C-5) — existence-only "author has starred this skill" marker, one row per
(namespace, name, author). Idempotent add/remove, mirroring the `ingest.py::upsert_release`
SAVEPOINT + IntegrityError-fallback pattern for the insert side (two concurrent "star"
clicks from the same user racing each other should both succeed, not raise).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from skillify.index.models import SkillStar


def add_star(session: Session, *, namespace: str, name: str, author: str, created_at: datetime) -> None:
    """Idempotent: starring an already-starred skill is a no-op success, not an error."""
    star = SkillStar(namespace=namespace, name=name, author=author, created_at=created_at)
    try:
        with session.begin_nested():
            session.add(star)
            session.flush()
        session.commit()
    except IntegrityError:
        session.rollback()
        # Another writer (or an earlier call) already created this row — already starred.


def remove_star(session: Session, *, namespace: str, name: str, author: str) -> None:
    """No-op if the skill wasn't starred by this author."""
    existing = session.execute(
        select(SkillStar).where(
            SkillStar.namespace == namespace, SkillStar.name == name, SkillStar.author == author
        )
    ).scalar_one_or_none()
    if existing is None:
        return
    session.delete(existing)
    session.commit()


def has_starred(session: Session, *, namespace: str, name: str, author: str) -> bool:
    existing = session.execute(
        select(SkillStar).where(
            SkillStar.namespace == namespace, SkillStar.name == name, SkillStar.author == author
        )
    ).scalar_one_or_none()
    return existing is not None


def star_counts(session: Session) -> dict[tuple[str, str], int]:
    """(namespace, name) -> total star count, across all users — mirrors
    `events.py::install_counts`'s batch-aggregation-into-a-dict pattern, for listing pages
    that need to show a star count per skill without one query per row."""
    stmt = select(SkillStar.namespace, SkillStar.name, func.count(SkillStar.id)).group_by(
        SkillStar.namespace, SkillStar.name
    )
    return {(ns, n): count for ns, n, count in session.execute(stmt)}
