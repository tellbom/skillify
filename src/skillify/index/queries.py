"""Read path: list/search the index (T2.2 acceptance: "新发布后 Web/搜索可查").

Kept intentionally simple — full search (Postgres full-text / Meilisearch) is T3.1's job
per PLAN.md §2; this only needs to prove the index is queryable, which the future Web
backend will build on.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from skillify.index.events import install_counts
from skillify.index.models import SkillIndexEntry
from skillify.index.ratings import rating_stats


def get_versions(session: Session, namespace: str, name: str) -> list[SkillIndexEntry]:
    stmt = (
        select(SkillIndexEntry)
        .where(SkillIndexEntry.namespace == namespace, SkillIndexEntry.name == name)
        .order_by(SkillIndexEntry.published_at.desc())
    )
    return list(session.execute(stmt).scalars())


def list_latest(session: Session) -> list[SkillIndexEntry]:
    """One row per (namespace, name) — the most recently published version of each."""
    latest_ids = select(func.max(SkillIndexEntry.id)).group_by(
        SkillIndexEntry.namespace, SkillIndexEntry.name
    )
    stmt = (
        select(SkillIndexEntry)
        .where(SkillIndexEntry.id.in_(latest_ids))
        .order_by(SkillIndexEntry.namespace, SkillIndexEntry.name)
    )
    return list(session.execute(stmt).scalars())


def search(session: Session, query: str) -> list[SkillIndexEntry]:
    """Substring match over name/description (case-insensitive), latest version per skill."""
    needle = query.lower()
    return [
        entry
        for entry in list_latest(session)
        if needle in entry.name.lower() or needle in entry.description.lower()
    ]


@dataclass
class LeaderboardRow:
    entry: SkillIndexEntry
    install_count: int
    rating_average: float | None
    rating_count: int


def leaderboard(session: Session, dimension: str) -> list[LeaderboardRow]:
    """T5.2 — one row per skill (latest published version), ranked by `dimension`:
    "installs" (total install events desc), "rating" (average rating desc, unrated last),
    or "recent" (published_at desc — same ordering `list_latest` already produces)."""
    if dimension not in ("installs", "rating", "recent"):
        raise ValueError(f"unknown leaderboard dimension {dimension!r}")

    entries = list_latest(session)
    counts = install_counts(session)
    stats = rating_stats(session)

    rows = [
        LeaderboardRow(
            entry=e,
            install_count=counts.get((e.namespace, e.name), 0),
            rating_average=stats.get((e.namespace, e.name), (None, 0))[0],
            rating_count=stats.get((e.namespace, e.name), (None, 0))[1],
        )
        for e in entries
    ]

    if dimension == "installs":
        rows.sort(key=lambda r: r.install_count, reverse=True)
    elif dimension == "rating":
        rows.sort(key=lambda r: (r.rating_average is not None, r.rating_average or 0), reverse=True)
    else:  # "recent"
        rows.sort(key=lambda r: r.entry.published_at, reverse=True)
    return rows
