"""Read path: list/search the index (T2.2 acceptance: "新发布后 Web/搜索可查").

Kept intentionally simple — full search (Postgres full-text / Meilisearch) is T3.1's job
per PLAN.md §2; this only needs to prove the index is queryable, which the future Web
backend will build on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, false, func, select
from sqlalchemy.orm import Session

from skillify.index.events import install_counts
from skillify.index.models import SkillEvent, SkillIndexEntry, SkillRating
from skillify.index.ratings import rating_stats

_WINDOW_DAYS = {"week": 7, "month": 30}
_SORT_COLUMNS = ("installs", "rating", "updated")


def get_versions(session: Session, namespace: str, name: str) -> list[SkillIndexEntry]:
    stmt = (
        select(SkillIndexEntry)
        .where(SkillIndexEntry.namespace == namespace, SkillIndexEntry.name == name)
        .order_by(SkillIndexEntry.published_at.desc())
    )
    return list(session.execute(stmt).scalars())


def _latest_ids_subquery(*, include_yanked: bool) -> Select:
    """The "most recently published version per (namespace, name)" id set, as a
    SQLAlchemy Core `select()` — a max(id) grouped over a (optionally yanked-filtered)
    subquery, same shape as `list_latest` used before this was factored out. Returns a
    scalar-column `select()` (of `id`) suitable for `.where(SkillIndexEntry.id.in_(...))`;
    shared by `list_latest` and `search` so both pick "latest" the same way. C-1: filtering
    `yanked` *before* the max(id) grouping is what gives skills the crates.io-style fallback
    (newest non-yanked version wins; an all-yanked skill drops out entirely)."""
    base = select(SkillIndexEntry)
    if not include_yanked:
        # DM8's SQLAlchemy dialect renders ``is_(False)`` as ``IS 0``, which DM8
        # rejects. Equality against SQLAlchemy's false literal compiles to ``= 0``.
        base = base.where(SkillIndexEntry.yanked == false())
    filtered = base.subquery()
    return select(func.max(filtered.c.id)).group_by(filtered.c.namespace, filtered.c.name)


def list_latest(session: Session, *, include_yanked: bool = False) -> list[SkillIndexEntry]:
    """One row per (namespace, name) — the most recently published version of each.

    C-1: by default excludes yanked rows *before* picking "most recent per skill" — if a
    skill's newest version is yanked, its "latest" falls back to the newest non-yanked
    version; if every version is yanked, the skill drops out of the list entirely
    (crates.io-style). `include_yanked=True` restores the old unfiltered behavior, for
    internal/admin use."""
    stmt = (
        select(SkillIndexEntry)
        .where(SkillIndexEntry.id.in_(_latest_ids_subquery(include_yanked=include_yanked)))
        .order_by(SkillIndexEntry.namespace, SkillIndexEntry.name)
    )
    return list(session.execute(stmt).scalars())


def _installs_subquery():
    """(namespace, name) -> total install-event count, as a SQLAlchemy subquery — the
    SQL-aggregate equivalent of `events.py::install_counts` (which loads+aggregates in
    Python and can't be reused here: `search`'s `sort="installs"` needs the count available
    as an orderable SQL column via `outerjoin`, not a Python dict)."""
    return (
        select(
            SkillEvent.namespace.label("namespace"),
            SkillEvent.name.label("name"),
            func.count(SkillEvent.id).label("install_count"),
        )
        .where(SkillEvent.event_type == "install")
        .group_by(SkillEvent.namespace, SkillEvent.name)
        .subquery()
    )


def _ratings_subquery():
    """(namespace, name) -> average rating, as a SQLAlchemy subquery — the SQL-aggregate
    equivalent of `ratings.py::rating_stats`, needed as an orderable SQL column for
    `sort="rating"` the same way `_installs_subquery` is needed for `sort="installs"`."""
    return (
        select(
            SkillRating.namespace.label("namespace"),
            SkillRating.name.label("name"),
            func.avg(SkillRating.score).label("rating_average"),
        )
        .group_by(SkillRating.namespace, SkillRating.name)
        .subquery()
    )


def search(
    session: Session,
    query: str | None = None,
    *,
    namespace: str | None = None,
    author: str | None = None,
    tags: list[str] | None = None,
    sort: str = "updated",
    page: int = 1,
    page_size: int = 20,
    include_yanked: bool = False,
) -> tuple[list[SkillIndexEntry], int]:
    """C-4: SQL-level search over the latest (non-yanked, unless `include_yanked`) version
    of each skill — filter/sort/paginate all pushed down to the database instead of loading
    every row into Python. Returns `(page_of_results, total_matching_count)`.

    Portability (the whole point of this function): every filter/sort/pagination clause
    below is a SQLAlchemy Core/ORM expression object (`.where()`, `.order_by()`,
    `.offset()`/`.limit()`, `outerjoin()`, `func.count()/func.avg()`, `func.lower(...).like(
    func.lower(...))`) — never a `text("...")` literal or an f-string SQL fragment. This
    matters because the production target (DM8) has real dialect differences from SQLite/
    Postgres around `LIKE` case-sensitivity and pagination syntax; staying on the expression
    API lets SQLAlchemy's dialect layer paper over those differences instead of us having to
    hand-write portable SQL. `query`'s name/description match uses `func.lower(col).like(
    func.lower(pattern))` rather than `.ilike()` specifically to make the "both sides
    lower-cased, then a plain LIKE" behavior explicit and independent of whether a given
    dialect's ILIKE/case-insensitivity semantics are trustworthy under DM8.

    `tags` filtering degrades to an application-layer path (deliberate, not an oversight):
    tags are stored as a JSON column, and JSON-function dialect support/semantics differ
    enough between SQLite/Postgres/DM8 that filtering on them in SQL was explicitly ruled
    out for this first version (see task brief). When `tags` is given, this function cannot
    paginate purely in SQL for the filtered set — instead it lets SQL narrow by namespace/
    author/text/sort/yanked first (same as the no-tags path), pulls *all* of those matching
    rows into Python, filters by tag intersection there, and only then slices the page
    manually. This means the "total" count and the page contents are both computed in Python
    for this one case, unlike the SQL-paginated common path below. Fine at intranet data
    volumes (see PLAN.md §4/§5); would need revisiting (e.g. a normalized tags table) if
    this table ever grew large enough for that to matter.
    """
    if sort not in _SORT_COLUMNS:
        raise ValueError(f"unknown sort {sort!r} (expected one of {_SORT_COLUMNS})")
    if page < 1:
        raise ValueError(f"page must be >= 1, got {page}")
    if page_size < 1:
        raise ValueError(f"page_size must be >= 1, got {page_size}")

    stmt = select(SkillIndexEntry).where(SkillIndexEntry.id.in_(_latest_ids_subquery(include_yanked=include_yanked)))

    if namespace is not None:
        stmt = stmt.where(SkillIndexEntry.namespace == namespace)
    if author is not None:
        stmt = stmt.where(SkillIndexEntry.author == author)
    if query:
        needle = f"%{query.lower()}%"
        stmt = stmt.where(
            func.lower(SkillIndexEntry.name).like(needle) | func.lower(SkillIndexEntry.description).like(needle)
        )

    if sort == "installs":
        installs = _installs_subquery()
        stmt = stmt.outerjoin(
            installs,
            (installs.c.namespace == SkillIndexEntry.namespace) & (installs.c.name == SkillIndexEntry.name),
        ).order_by(func.coalesce(installs.c.install_count, 0).desc(), SkillIndexEntry.namespace, SkillIndexEntry.name)
    elif sort == "rating":
        ratings = _ratings_subquery()
        stmt = stmt.outerjoin(
            ratings,
            (ratings.c.namespace == SkillIndexEntry.namespace) & (ratings.c.name == SkillIndexEntry.name),
        ).order_by(ratings.c.rating_average.is_(None), ratings.c.rating_average.desc(), SkillIndexEntry.namespace, SkillIndexEntry.name)
    else:  # "updated"
        stmt = stmt.order_by(SkillIndexEntry.published_at.desc())

    if tags:
        # Degraded path — see docstring. SQL has already narrowed by namespace/author/query/
        # sort/yanked above; tags + pagination both happen here in Python.
        wanted = set(tags)
        matched = [e for e in session.execute(stmt).scalars() if wanted.issubset(set(e.tags))]
        total = len(matched)
        start = (page - 1) * page_size
        return matched[start : start + page_size], total

    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    page_stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list(session.execute(page_stmt).scalars()), total


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
