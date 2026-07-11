"""Skill subscriptions (C-5) — existence-only "author wants to know about new versions of
this skill" marker, one row per (namespace, name, author). Structurally identical to
`star.py` (see `SkillSubscription` in models.py for why it's a separate table rather than a
column on `SkillStar`); idempotent add/remove with the same SAVEPOINT pattern.

Deliberately does not do any notification/unread tracking — the source task doc explicitly
defers a `notifications` table to a later phase. This module only answers "who is
subscribed to what" and "what is a given user subscribed to" (see `list_subscriptions_for_user`,
which the web layer joins against `queries.get_versions`/`list_latest` to build the
"my subscriptions" snapshot view — subscribing does not persist a snapshot of the version at
subscribe time).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from skillify.index.models import SkillSubscription


def add_subscription(session: Session, *, namespace: str, name: str, author: str, created_at: datetime) -> None:
    """Idempotent: subscribing to an already-subscribed skill is a no-op success."""
    subscription = SkillSubscription(namespace=namespace, name=name, author=author, created_at=created_at)
    try:
        with session.begin_nested():
            session.add(subscription)
            session.flush()
        session.commit()
    except IntegrityError:
        session.rollback()


def remove_subscription(session: Session, *, namespace: str, name: str, author: str) -> None:
    """No-op if the skill wasn't subscribed to by this author."""
    existing = session.execute(
        select(SkillSubscription).where(
            SkillSubscription.namespace == namespace,
            SkillSubscription.name == name,
            SkillSubscription.author == author,
        )
    ).scalar_one_or_none()
    if existing is None:
        return
    session.delete(existing)
    session.commit()


def is_subscribed(session: Session, *, namespace: str, name: str, author: str) -> bool:
    existing = session.execute(
        select(SkillSubscription).where(
            SkillSubscription.namespace == namespace,
            SkillSubscription.name == name,
            SkillSubscription.author == author,
        )
    ).scalar_one_or_none()
    return existing is not None


def list_subscriptions_for_user(session: Session, author: str) -> list[tuple[str, str]]:
    """(namespace, name) pairs `author` is subscribed to, for the "my subscriptions" page."""
    stmt = select(SkillSubscription.namespace, SkillSubscription.name).where(
        SkillSubscription.author == author
    )
    return [(ns, n) for ns, n in session.execute(stmt)]
