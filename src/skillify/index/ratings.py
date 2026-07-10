"""Skill ratings — one 1-5 score per (user, skill), upserted on re-rating (T5.2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from skillify.index.models import SkillRating


def upsert_rating(
    session: Session, *, namespace: str, name: str, author: str, score: int, created_at: datetime
) -> SkillRating:
    if not 1 <= score <= 5:
        raise ValueError(f"score must be 1-5, got {score}")
    existing = session.execute(
        select(SkillRating).where(
            SkillRating.namespace == namespace, SkillRating.name == name, SkillRating.author == author
        )
    ).scalar_one_or_none()
    if existing is None:
        rating = SkillRating(namespace=namespace, name=name, author=author, score=score, created_at=created_at)
        session.add(rating)
        session.flush()
        return rating
    existing.score = score
    existing.created_at = created_at
    return existing


def rating_stats(session: Session) -> dict[tuple[str, str], tuple[float, int]]:
    """(namespace, name) -> (average score, count), across all raters."""
    stmt = select(
        SkillRating.namespace, SkillRating.name, func.avg(SkillRating.score), func.count(SkillRating.id)
    ).group_by(SkillRating.namespace, SkillRating.name)
    return {(ns, n): (float(avg), count) for ns, n, avg, count in session.execute(stmt)}
