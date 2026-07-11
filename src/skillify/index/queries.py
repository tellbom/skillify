"""Read path: list/search the index (T2.2 acceptance: "新发布后 Web/搜索可查").

Kept intentionally simple — full search (Postgres full-text / Meilisearch) is T3.1's job
per PLAN.md §2; this only needs to prove the index is queryable, which the future Web
backend will build on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from skillify.index.events import install_counts
from skillify.index.models import SkillIndexEntry
from skillify.index.ratings import rating_stats

_WINDOW_DAYS = {"week": 7, "month": 30}


def get_versions(session: Session, namespace: str, name: str) -> list[SkillIndexEntry]:
    stmt = (
        select(SkillIndexEntry)
        .where(SkillIndexEntry.namespace == namespace, SkillIndexEntry.name == name)
        .order_by(SkillIndexEntry.published_at.desc())
    )
    return list(session.execute(stmt).scalars())


def list_latest(session: Session, *, include_yanked: bool = False) -> list[SkillIndexEntry]:
    """One row per (namespace, name) — the most recently published version of each.

    C-1: by default excludes yanked rows *before* picking "most recent per skill" — if a
    skill's newest version is yanked, its "latest" falls back to the newest non-yanked
    version; if every version is yanked, the skill drops out of the list entirely
    (crates.io-style). `include_yanked=True` restores the old unfiltered behavior, for
    internal/admin use."""
    base = select(SkillIndexEntry)
    if not include_yanked:
        base = base.where(SkillIndexEntry.yanked.is_(False))
    filtered = base.subquery()
    latest_ids = select(func.max(filtered.c.id)).group_by(filtered.c.namespace, filtered.c.name)
    stmt = (
        select(SkillIndexEntry)
        .where(SkillIndexEntry.id.in_(latest_ids))
        .order_by(SkillIndexEntry.namespace, SkillIndexEntry.name)
    )
    return list(session.execute(stmt).scalars())


def search(session: Session, query: str, *, include_yanked: bool = False) -> list[SkillIndexEntry]:
    """Substring match over name/description (case-insensitive), latest version per skill."""
    needle = query.lower()
    return [
        entry
        for entry in list_latest(session, include_yanked=include_yanked)
        if needle in entry.name.lower() or needle in entry.description.lower()
    ]


@dataclass
class LeaderboardRow:
    entry: SkillIndexEntry
    install_count: int
    rating_average: float | None
    rating_count: int


def leaderboard(
    session: Session, dimension: str, *, window: str = "all", include_yanked: bool = False
) -> list[LeaderboardRow]:
    """T5.2 — one row per skill (latest published version), ranked by `dimension`:
    "installs" (total install events desc), "rating" (average rating desc, unrated last),
    or "recent" (published_at desc — same ordering `list_latest` already produces).

    C-6: `window` ("week" | "month" | "all") restricts the "installs" dimension's counts to
    events in the last 7/30 days (or unrestricted for "all") — cutoff is computed here in
    Python and passed to `install_counts` as a plain bound parameter, never a DB-side date
    function, so the comparison stays portable across SQLite/Postgres/DM8. `rating`/`recent`
    ignore `window`: an average rating or a publish date don't have a meaningful "this week's
    value" distinct from their all-time value, so windowing them isn't attempted here."""
    if dimension not in ("installs", "rating", "recent"):
        raise ValueError(f"unknown leaderboard dimension {dimension!r}")
    if window not in ("week", "month", "all"):
        raise ValueError(f"unknown leaderboard window {window!r}")

    entries = list_latest(session, include_yanked=include_yanked)
    since = None
    if dimension == "installs" and window in _WINDOW_DAYS:
        since = datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS[window])
    counts = install_counts(session, since=since)
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
