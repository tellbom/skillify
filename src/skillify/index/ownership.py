"""Namespace ownership for the web-upload path (M-C, docs/review-m2-m6.md).

First-publish-wins: the first successful upload into a namespace claims it for that
Keycloak user; later uploads into the same namespace must come from the same user. This
is a real security gate (not best-effort like `_index_release`) — a claim (or a rejection)
happens in the same transaction as the check to avoid a check-then-act race between two
concurrent first-time uploads into the same namespace.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from skillify.index.models import SkillNamespaceOwner


class NamespaceOwnershipError(Exception):
    def __init__(self, namespace: str, owner_username: str):
        super().__init__(f"namespace {namespace!r} is already owned by {owner_username!r}")
        self.namespace = namespace
        self.owner_username = owner_username


def claim_or_verify_namespace(session: Session, *, namespace: str, username: str, claimed_at: datetime) -> None:
    """Raise `NamespaceOwnershipError` if `namespace` is owned by someone else; otherwise
    claim it for `username` (no-op if already owned by `username`). Commits its own
    transaction so the claim is durable even if the caller's publish fails afterward —
    losing a race to claim a namespace should not let the loser publish into it anyway."""
    existing = session.execute(
        select(SkillNamespaceOwner).where(SkillNamespaceOwner.namespace == namespace)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.owner_username != username:
            raise NamespaceOwnershipError(namespace, existing.owner_username)
        return

    session.add(SkillNamespaceOwner(namespace=namespace, owner_username=username, claimed_at=claimed_at))
    try:
        session.commit()
    except IntegrityError:
        # Lost a race against a concurrent first claim of the same namespace.
        session.rollback()
        winner = session.execute(
            select(SkillNamespaceOwner).where(SkillNamespaceOwner.namespace == namespace)
        ).scalar_one()
        if winner.owner_username != username:
            raise NamespaceOwnershipError(namespace, winner.owner_username) from None


def release_namespace(session: Session, *, namespace: str, expected_owner: str) -> bool:
    """Delete one ownership row only when both namespace and current owner match."""
    result = session.execute(
        delete(SkillNamespaceOwner).where(
            SkillNamespaceOwner.namespace == namespace,
            SkillNamespaceOwner.owner_username == expected_owner,
        )
    )
    return bool(result.rowcount)
