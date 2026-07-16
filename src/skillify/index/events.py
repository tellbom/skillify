"""Install/run event recording (T5.2 install counts for leaderboard; T6.2 run reports)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from skillify.index.models import SkillEvent


def record_event(
    session: Session,
    *,
    namespace: str,
    name: str,
    version: str,
    event_type: str,
    occurred_at: datetime,
    success: bool | None = None,
    machine_id: str | None = None,
) -> SkillEvent:
    if event_type not in ("install", "run", "uninstall", "feedback"):
        raise ValueError(
            f"unknown event_type {event_type!r} "
            "(expected install, run, uninstall, or feedback)"
        )
    event = SkillEvent(
        namespace=namespace, name=name, version=version, event_type=event_type,
        success=success, machine_id=machine_id, occurred_at=occurred_at,
    )
    session.add(event)
    session.flush()
    return event


def install_counts(session: Session, *, since: datetime | None = None) -> dict[tuple[str, str], int]:
    """(namespace, name) -> total install event count, across all versions.

    `since`, if given, restricts to events with `occurred_at >= since` (C-6 leaderboard
    time windows). This is a plain parameter comparison — the cutoff is computed in Python
    by the caller and bound as an ordinary value, no DB-side date/time function involved, so
    it's portable across SQLite/Postgres/DM8 without any dialect-specific date arithmetic."""
    stmt = (
        select(SkillEvent.namespace, SkillEvent.name, func.count(SkillEvent.id))
        .where(SkillEvent.event_type == "install")
    )
    if since is not None:
        stmt = stmt.where(SkillEvent.occurred_at >= since)
    stmt = stmt.group_by(SkillEvent.namespace, SkillEvent.name)
    return {(ns, n): count for ns, n, count in session.execute(stmt)}
