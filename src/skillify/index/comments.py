"""Comment CRUD for T5.1 (skill_comments table); C-5 adds one-level-deep replies
(`parent_id`, self-referencing, no DB foreign key — consistent with this table's existing
no-FK convention) and soft-delete.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from skillify.index.models import SkillComment

_DELETED_PLACEHOLDER = "[已删除]"


class CommentNotFoundError(Exception):
    def __init__(self, comment_id: int):
        super().__init__(f"comment {comment_id} not found")
        self.comment_id = comment_id


class CommentPermissionError(Exception):
    """Raised when someone other than the comment's author or the skill's namespace owner
    tries to soft-delete a comment — follows the `NamespaceOwnershipError` style (a plain
    `Exception` subclass, mapped to an HTTP status by the web layer) rather than reusing the
    stdlib `PermissionError`, so the web layer can catch it specifically without also
    catching unrelated OS-level permission errors."""

    def __init__(self, comment_id: int, actor_username: str):
        super().__init__(f"{actor_username} may not delete comment {comment_id} (not the author or namespace owner)")
        self.comment_id = comment_id
        self.actor_username = actor_username


def add_comment(
    session: Session,
    *,
    namespace: str,
    name: str,
    author: str,
    body: str,
    created_at,
    parent_id: int | None = None,
) -> SkillComment:
    if parent_id is not None:
        parent = session.execute(select(SkillComment).where(SkillComment.id == parent_id)).scalar_one_or_none()
        if parent is None or parent.namespace != namespace or parent.name != name:
            raise ValueError(f"parent comment {parent_id} does not belong to {namespace}/{name}")
    comment = SkillComment(
        namespace=namespace, name=name, author=author, body=body, created_at=created_at, parent_id=parent_id
    )
    session.add(comment)
    session.flush()
    return comment


def list_comments(session: Session, namespace: str, name: str) -> list[SkillComment]:
    """Raw rows, deleted or not, body untouched — callers that need the soft-delete display
    rule applied should use `list_comments_for_display` instead."""
    stmt = (
        select(SkillComment)
        .where(SkillComment.namespace == namespace, SkillComment.name == name)
        .order_by(SkillComment.created_at.asc())
    )
    return list(session.execute(stmt).scalars())


def list_comments_for_display(session: Session, namespace: str, name: str) -> list[SkillComment]:
    """Same rows/order as `list_comments`, but any `deleted=True` comment has its `body`
    replaced with a placeholder — `id`/`parent_id`/`author`/`created_at` are left intact so
    the tree structure stays renderable (a deleted comment may still have live replies under
    it). Kept here (index layer) rather than in the web layer so both the FastAPI endpoint
    and any future consumer (e.g. a CLI) get the same soft-delete display rule for free."""
    comments = list_comments(session, namespace, name)
    for comment in comments:
        if comment.deleted:
            comment.body = _DELETED_PLACEHOLDER
    return comments


def soft_delete_comment(
    session: Session, *, comment_id: int, actor_username: str, is_namespace_owner: bool
) -> SkillComment:
    """Soft-delete: sets `deleted=True` in place (row/body kept for tree rendering; the
    placeholder substitution happens at read time in `list_comments_for_display`, not here).

    Only the comment's own author or the skill's namespace owner may delete it — the two
    halves of this check come from different places: `comment.author == actor_username` is
    compared directly against the comment row (comment authorship, not skill authorship),
    while `is_namespace_owner` is supplied by the caller, which is expected to have checked
    it via the same "author or namespace owner" pattern Task 1's `yank.py::can_manage_version`
    established for versions (that function checks the namespace-owner half only; it has no
    notion of "comment author" and is not reused here for that half).

    Raises `CommentNotFoundError` if the comment doesn't exist, `CommentPermissionError` if
    the actor is neither the author nor the namespace owner — deletion attempts that aren't
    allowed must fail loudly, not silently no-op."""
    comment = session.execute(select(SkillComment).where(SkillComment.id == comment_id)).scalar_one_or_none()
    if comment is None:
        raise CommentNotFoundError(comment_id)
    if comment.author != actor_username and not is_namespace_owner:
        raise CommentPermissionError(comment_id, actor_username)
    comment.deleted = True
    session.commit()
    return comment
