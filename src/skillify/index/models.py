"""SQLAlchemy models for the five Skillify DM8 business tables.

The schema is initialized by ``infra/dm8-init/01-skillify-schema.sql`` and is physically
separate from Forgejo's PostgreSQL database.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SkillIndexEntry(Base):
    __tablename__ = "skill_index"
    __table_args__ = (UniqueConstraint("namespace", "name", "version", name="uq_skill_index_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500), default="")
    author: Mapped[str] = mapped_column(String(255), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    checksum: Mapped[str] = mapped_column(String(64))
    release_url: Mapped[str] = mapped_column(String(1024), default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # T6.3: skill.yaml's free-form `orchestration` field (spec §3), carried through so a
    # future orchestrator can query it without re-fetching the artifact from Forgejo. Not
    # interpreted/validated beyond "must be a JSON object" (already enforced at manifest
    # validation time, T0.2) — no orchestration engine is implemented here.
    orchestration: Mapped[dict] = mapped_column(JSON, default=dict)
    # C-1 (version center): a yanked version stays installable if explicitly requested
    # (by tag/version) but drops out of "latest" resolution (list_latest/search/leaderboard)
    # — crates.io-style semantics. Unlike SkillEvent.success this is NOT nullable/tri-state:
    # every row has a concrete yanked/not-yanked status from the moment it's inserted.
    yanked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SkillIndexEntry {self.namespace}/{self.name}@{self.version}>"


class SkillComment(Base):
    """T5.1 — flat (no threading) comments on a skill's detail page."""

    __tablename__ = "skill_comments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    author: Mapped[str] = mapped_column(String(255))  # Keycloak preferred_username/sub
    body: Mapped[str] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

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
