"""Comment CRUD for T5.1 (skill_comments table)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from skillify.index.models import SkillComment


def add_comment(session: Session, *, namespace: str, name: str, author: str, body: str, created_at) -> SkillComment:
    comment = SkillComment(namespace=namespace, name=name, author=author, body=body, created_at=created_at)
    session.add(comment)
    session.flush()
    return comment


def list_comments(session: Session, namespace: str, name: str) -> list[SkillComment]:
    stmt = (
        select(SkillComment)
        .where(SkillComment.namespace == namespace, SkillComment.name == name)
        .order_by(SkillComment.created_at.asc())
    )
    return list(session.execute(stmt).scalars())
