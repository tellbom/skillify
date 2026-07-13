"""SQLAlchemy models for the five Skillify DM8 business tables.

The schema is initialized by ``infra/dm8-init/01-skillify-schema.sql`` and is physically
separate from Forgejo's PostgreSQL database.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class JSONText(TypeDecorator[Any]):
    """JSON encoded as text, matching the DM8 CLOB schema fact source."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        return None if value is None else json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None or not isinstance(value, str):
            return value
        return json.loads(value)


class SkillIndexEntry(Base):
    __tablename__ = "skill_index"
    __table_args__ = (UniqueConstraint("namespace", "name", "version", name="uq_skill_index_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500), default="")
    # C-4: indexed because `queries.py::search`'s `author` filter is now a SQL-level
    # `.where(SkillIndexEntry.author == author)` equality match (see infra/dm8-init/
    # 05-c4-search-indexes.sql for the DM8-side equivalent, since DM8 doesn't pick up
    # SQLAlchemy's `Base.metadata.create_all` the way SQLite/Postgres do in this project).
    author: Mapped[str] = mapped_column(String(255), default="", index=True)
    tags: Mapped[list] = mapped_column(JSONText(), default=list)
    checksum: Mapped[str] = mapped_column(String(64))
    release_url: Mapped[str] = mapped_column(String(1024), default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # T6.3: skill.yaml's free-form `orchestration` field (spec §3), carried through so a
    # future orchestrator can query it without re-fetching the artifact from Forgejo. Not
    # interpreted/validated beyond "must be a JSON object" (already enforced at manifest
    # validation time, T0.2) — no orchestration engine is implemented here.
    orchestration: Mapped[dict] = mapped_column(JSONText(), default=dict)
    # C-1 (version center): a yanked version stays installable if explicitly requested
    # (by tag/version) but drops out of "latest" resolution (list_latest/search/leaderboard)
    # — crates.io-style semantics. Unlike SkillEvent.success this is NOT nullable/tri-state:
    # every row has a concrete yanked/not-yanked status from the moment it's inserted.
    yanked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SkillIndexEntry {self.namespace}/{self.name}@{self.version}>"


class SkillComment(Base):
    """T5.1 — flat (no threading) comments on a skill's detail page.

    C-5: `parent_id` adds one level of self-referencing tree structure (NULL = top-level
    comment; non-NULL = a reply to another comment in the same (namespace, name) — validated
    in the application layer at write time, see `comments.py::add_comment`). No DB foreign
    key on `parent_id`, consistent with this table (and this whole schema) never using FKs
    even for its other logical parent-child relationships. `deleted` is a soft-delete flag:
    a deleted comment's row stays (so replies keep a valid tree to render against) but its
    body is replaced with a placeholder at read time (see `list_comments_for_display`)."""

    __tablename__ = "skill_comments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    author: Mapped[str] = mapped_column(String(255))  # Keycloak preferred_username/sub
    body: Mapped[str] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parent_id: Mapped[int | None] = mapped_column(Integer, default=None)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SkillComment {self.namespace}/{self.name} by {self.author}>"


class SkillRating(Base):
    """T5.2 — one 1-5 rating per (user, skill); re-rating updates in place (upsert)."""

    __tablename__ = "skill_ratings"
    __table_args__ = (UniqueConstraint("namespace", "name", "author", name="uq_skill_rating_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    author: Mapped[str] = mapped_column(String(255))
    score: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SkillRating {self.namespace}/{self.name} {self.score} by {self.author}>"


class SkillStar(Base):
    """C-5 — one row per (namespace, name, author) means "author has starred this skill";
    absence of a row means not starred. No score field (unlike `SkillRating`) — existence
    is the only signal. `star_counts` (events.py-style batch aggregation) powers the star
    count shown on listing/detail pages."""

    __tablename__ = "skill_stars"
    __table_args__ = (UniqueConstraint("namespace", "name", "author", name="uq_skill_star_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    author: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SkillStar {self.namespace}/{self.name} by {self.author}>"


class SkillSubscription(Base):
    """C-5 — one row per (namespace, name, author) means "author is subscribed to new
    versions of this skill". Structurally identical to `SkillStar` (existence-only, no
    score); kept as a separate table because star and subscribe are independent actions
    (you can star without subscribing and vice versa) even though the row shape is the
    same, matching the source task doc's explicit "two tables, same shape" design."""

    __tablename__ = "skill_subscriptions"
    __table_args__ = (UniqueConstraint("namespace", "name", "author", name="uq_skill_subscription_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    author: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SkillSubscription {self.namespace}/{self.name} by {self.author}>"


class SkillNamespaceOwner(Base):
    """M-C (docs/review-m2-m6.md) — first-publish-wins ownership of a `namespace` for the
    web-upload path (the shared Forgejo service account otherwise lets any logged-in user
    publish into anyone else's namespace). `owner_username` is the Keycloak
    `preferred_username`/`sub` claim of whoever first published into this namespace via
    `POST /api/skills/upload`; later uploads into the same namespace must match. Does not
    apply to the webhook/CI path, which already pins `org_override` to the Forgejo repo's
    actual owner (a stronger, independent check)."""

    __tablename__ = "skill_namespace_owners"

    namespace: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_username: Mapped[str] = mapped_column(String(255))
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SkillNamespaceOwner {self.namespace} owned by {self.owner_username}>"


class SkillPublishJob(Base):
    """C-2 (`skill_publish_jobs`) — records the outcome of the most recent publish attempt
    for a given (namespace, name, version), keyed by who triggered it (`initiator`, a
    Keycloak `preferred_username`/`sub`). This is the data source for "my failed
    publishes": scanning every Forgejo repo for stranded draft releases across every
    namespace is not feasible (see `publisher.py`'s A-2 draft-resume mechanism for why a
    stranded draft can exist at all), so instead the formal web publish path
    (`formal_publish.py`) writes one row per attempt here.

    `UniqueConstraint(namespace, name, version, initiator)`: a retry of the same version by
    the same user updates that user's row in place. Attempts by different users remain
    isolated so an ownership failure cannot replace the owner's publish result."""

    __tablename__ = "skill_publish_jobs"
    __table_args__ = (
        UniqueConstraint("namespace", "name", "version", "initiator", name="uq_skill_publish_job_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(64))
    initiator: Mapped[str] = mapped_column(String(255), index=True)  # Keycloak preferred_username/sub
    status: Mapped[str] = mapped_column(String(16))  # "succeeded" | "failed"
    error_message: Mapped[str | None] = mapped_column(String(2000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SkillPublishJob {self.namespace}/{self.name}@{self.version} {self.status} by {self.initiator}>"


class SkillEvent(Base):
    """T5.2 (install count for the leaderboard) + T6.2 (client->server run report stub)
    share this table, distinguished by `event_type`. Deliberately minimal columns — see
    TASKS.md T6.2 for the documented privacy boundary (no PII beyond an opaque machine id
    the client itself generates, no payloads/args/output captured)."""

    __tablename__ = "skill_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(16), index=True)  # "install" | "run"
    success: Mapped[bool | None] = mapped_column(default=None)  # only meaningful for "run"
    machine_id: Mapped[str | None] = mapped_column(String(128), default=None)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SkillEvent {self.event_type} {self.namespace}/{self.name}@{self.version}>"
