"""Tests for C-5 — star/subscribe (star.py/subscriptions.py) and comment reply/soft-delete
(comments.py), run against SQLite."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from skillify.index.comments import (
    CommentNotFoundError,
    CommentPermissionError,
    add_comment,
    list_comments_for_display,
    soft_delete_comment,
)
from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.models import SkillComment
from skillify.index.star import add_star, has_starred, remove_star, star_counts
from skillify.index.subscriptions import (
    add_subscription,
    is_subscribed,
    list_subscriptions_for_user,
    remove_subscription,
)


@pytest.fixture()
def engine():
    eng = make_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- star.py ---------------------------------------------------------------


def test_add_star_is_idempotent(engine) -> None:
    with session_scope(engine) as session:
        add_star(session, namespace="excel", name="pivot-analysis", author="jane", created_at=_now())
        add_star(session, namespace="excel", name="pivot-analysis", author="jane", created_at=_now())
        assert has_starred(session, namespace="excel", name="pivot-analysis", author="jane") is True
        assert star_counts(session).get(("excel", "pivot-analysis")) == 1


def test_remove_star_is_noop_when_absent(engine) -> None:
    with session_scope(engine) as session:
        remove_star(session, namespace="excel", name="pivot-analysis", author="jane")
        assert has_starred(session, namespace="excel", name="pivot-analysis", author="jane") is False


def test_star_add_then_remove(engine) -> None:
    with session_scope(engine) as session:
        add_star(session, namespace="excel", name="pivot-analysis", author="jane", created_at=_now())
        remove_star(session, namespace="excel", name="pivot-analysis", author="jane")
        assert has_starred(session, namespace="excel", name="pivot-analysis", author="jane") is False
        assert star_counts(session).get(("excel", "pivot-analysis"), 0) == 0


def test_star_counts_aggregate_across_users(engine) -> None:
    with session_scope(engine) as session:
        add_star(session, namespace="excel", name="pivot-analysis", author="jane", created_at=_now())
        add_star(session, namespace="excel", name="pivot-analysis", author="bob", created_at=_now())
        add_star(session, namespace="text", name="word-frequency", author="jane", created_at=_now())
        counts = star_counts(session)
        assert counts[("excel", "pivot-analysis")] == 2
        assert counts[("text", "word-frequency")] == 1


# --- subscriptions.py --------------------------------------------------------


def test_add_subscription_is_idempotent(engine) -> None:
    with session_scope(engine) as session:
        add_subscription(session, namespace="excel", name="pivot-analysis", author="jane", created_at=_now())
        add_subscription(session, namespace="excel", name="pivot-analysis", author="jane", created_at=_now())
        assert is_subscribed(session, namespace="excel", name="pivot-analysis", author="jane") is True


def test_remove_subscription_is_noop_when_absent(engine) -> None:
    with session_scope(engine) as session:
        remove_subscription(session, namespace="excel", name="pivot-analysis", author="jane")
        assert is_subscribed(session, namespace="excel", name="pivot-analysis", author="jane") is False


def test_list_subscriptions_for_user(engine) -> None:
    with session_scope(engine) as session:
        add_subscription(session, namespace="excel", name="pivot-analysis", author="jane", created_at=_now())
        add_subscription(session, namespace="text", name="word-frequency", author="jane", created_at=_now())
        add_subscription(session, namespace="text", name="word-frequency", author="bob", created_at=_now())
        jane_subs = set(list_subscriptions_for_user(session, "jane"))
        assert jane_subs == {("excel", "pivot-analysis"), ("text", "word-frequency")}
        bob_subs = list_subscriptions_for_user(session, "bob")
        assert bob_subs == [("text", "word-frequency")]


# --- comments.py: reply (parent_id) ------------------------------------------


def test_add_comment_without_parent_is_top_level(engine) -> None:
    with session_scope(engine) as session:
        comment = add_comment(
            session, namespace="excel", name="pivot-analysis", author="jane", body="great skill", created_at=_now()
        )
        assert comment.parent_id is None


def test_add_reply_to_valid_parent(engine) -> None:
    with session_scope(engine) as session:
        top = add_comment(
            session, namespace="excel", name="pivot-analysis", author="jane", body="great skill", created_at=_now()
        )
        reply = add_comment(
            session, namespace="excel", name="pivot-analysis", author="bob", body="agreed",
            created_at=_now(), parent_id=top.id,
        )
        assert reply.parent_id == top.id


def test_reply_to_parent_in_different_skill_rejected(engine) -> None:
    with session_scope(engine) as session:
        top = add_comment(
            session, namespace="excel", name="pivot-analysis", author="jane", body="great skill", created_at=_now()
        )
        with pytest.raises(ValueError):
            add_comment(
                session, namespace="text", name="word-frequency", author="bob", body="wrong skill",
                created_at=_now(), parent_id=top.id,
            )


def test_reply_to_nonexistent_parent_rejected(engine) -> None:
    with session_scope(engine) as session:
        with pytest.raises(ValueError):
            add_comment(
                session, namespace="excel", name="pivot-analysis", author="bob", body="orphan reply",
                created_at=_now(), parent_id=999,
            )


# --- comments.py: soft delete -------------------------------------------------


def test_soft_delete_by_author(engine) -> None:
    with session_scope(engine) as session:
        comment = add_comment(
            session, namespace="excel", name="pivot-analysis", author="jane", body="great skill", created_at=_now()
        )
        deleted = soft_delete_comment(session, comment_id=comment.id, actor_username="jane", is_namespace_owner=False)
        assert deleted.deleted is True


def test_soft_delete_by_namespace_owner(engine) -> None:
    with session_scope(engine) as session:
        comment = add_comment(
            session, namespace="excel", name="pivot-analysis", author="jane", body="great skill", created_at=_now()
        )
        deleted = soft_delete_comment(session, comment_id=comment.id, actor_username="owner", is_namespace_owner=True)
        assert deleted.deleted is True


def test_soft_delete_rejected_for_non_author_non_owner(engine) -> None:
    with session_scope(engine) as session:
        comment = add_comment(
            session, namespace="excel", name="pivot-analysis", author="jane", body="great skill", created_at=_now()
        )
        with pytest.raises(CommentPermissionError):
            soft_delete_comment(session, comment_id=comment.id, actor_username="mallory", is_namespace_owner=False)
        # not silently no-op'd — the row must remain undeleted after the rejected attempt
        session.refresh(comment)
        assert comment.deleted is False


def test_soft_delete_nonexistent_comment_raises(engine) -> None:
    with session_scope(engine) as session:
        with pytest.raises(CommentNotFoundError):
            soft_delete_comment(session, comment_id=999, actor_username="jane", is_namespace_owner=False)


def test_list_comments_for_display_replaces_deleted_body_but_keeps_tree(engine) -> None:
    with session_scope(engine) as session:
        top = add_comment(
            session, namespace="excel", name="pivot-analysis", author="jane", body="great skill", created_at=_now()
        )
        reply = add_comment(
            session, namespace="excel", name="pivot-analysis", author="bob", body="agreed",
            created_at=_now(), parent_id=top.id,
        )
        soft_delete_comment(session, comment_id=top.id, actor_username="jane", is_namespace_owner=False)

        displayed = list_comments_for_display(session, "excel", "pivot-analysis")
        by_id = {c.id: c for c in displayed}
        assert by_id[top.id].deleted is True
        assert by_id[top.id].body == "[已删除]"
        assert by_id[top.id].id == top.id  # id/author/created_at preserved
        assert by_id[top.id].author == "jane"
        # the reply is untouched and still points at the (now-deleted) parent — tree intact
        assert by_id[reply.id].deleted is False
        assert by_id[reply.id].body == "agreed"
        assert by_id[reply.id].parent_id == top.id
        top_id = top.id

    # Regression test: list_comments_for_display must NOT mutate the tracked ORM instances'
    # `body` in place. The block above ran inside a `session_scope`, which commits on normal
    # exit — if the placeholder substitution had touched the session-tracked `SkillComment`
    # objects (rather than returning detached `CommentForDisplay` values), that commit would
    # have persisted "[已删除]" over the real comment text. Verify by re-querying the row from
    # a fresh session: the stored body must still be the original text.
    with session_scope(engine) as session:
        stored = session.execute(select(SkillComment).where(SkillComment.id == top_id)).scalar_one()
        assert stored.body == "great skill"
        assert stored.deleted is True
