"""Small SQLAlchemy claim/lease state machine for endpoint tasks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, false, or_, select, update
from sqlalchemy.orm import Session

from skillify.index.models import EndpointTaskRecord, WorkPackageRecord


class LeaseError(RuntimeError):
    pass


def _is_false(column):
    """Render a portable boolean comparison (DM8 rejects ``IS 0``)."""
    return column == false()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def claim_next_task(
    session: Session,
    *,
    endpoint_id: str,
    lease_owner: str,
    now: datetime,
    lease_seconds: int = 60,
) -> EndpointTaskRecord | None:
    now = _utc(now)
    has_unconfirmed_package = exists(select(WorkPackageRecord.id).where(
        WorkPackageRecord.task_id == EndpointTaskRecord.task_id,
        _is_false(WorkPackageRecord.confirmed),
    ))
    active = session.scalar(select(EndpointTaskRecord).where(
        EndpointTaskRecord.endpoint_id == endpoint_id,
        EndpointTaskRecord.lease_owner == lease_owner,
        EndpointTaskRecord.lease_expires_at > now,
        EndpointTaskRecord.state.in_(("awaiting_confirmation", "running")),
        _is_false(EndpointTaskRecord.revoked),
    ).order_by(EndpointTaskRecord.created_at))
    if active is not None:
        return active
    candidate = session.scalar(select(EndpointTaskRecord).where(
        EndpointTaskRecord.endpoint_id == endpoint_id,
        EndpointTaskRecord.state == "awaiting_confirmation",
        _is_false(EndpointTaskRecord.revoked),
        ~has_unconfirmed_package,
        or_(EndpointTaskRecord.lease_owner.is_(None), EndpointTaskRecord.lease_expires_at <= now),
    ).order_by(EndpointTaskRecord.created_at))
    if candidate is None:
        return None
    expires = now + timedelta(seconds=lease_seconds)
    changed = session.execute(update(EndpointTaskRecord).where(
        EndpointTaskRecord.task_id == candidate.task_id,
        EndpointTaskRecord.state_version == candidate.state_version,
        _is_false(EndpointTaskRecord.revoked),
        ~has_unconfirmed_package,
        or_(EndpointTaskRecord.lease_owner.is_(None), EndpointTaskRecord.lease_expires_at <= now),
    ).values(
        lease_owner=lease_owner,
        lease_expires_at=expires,
        heartbeat_at=now,
        state_version=EndpointTaskRecord.state_version + 1,
        updated_at=now,
    ).execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        return None
    session.flush()
    session.expire(candidate)
    return candidate


def heartbeat_task(
    session: Session,
    *,
    task_id: str,
    endpoint_id: str,
    lease_owner: str,
    now: datetime,
    lease_seconds: int = 60,
) -> EndpointTaskRecord:
    now = _utc(now)
    task = session.get(EndpointTaskRecord, task_id)
    if task is None or task.endpoint_id != endpoint_id:
        raise LeaseError("task is not assigned to this endpoint")
    expires_at = None if task.lease_expires_at is None else _utc(task.lease_expires_at)
    if task.lease_owner != lease_owner or expires_at is None or expires_at <= now:
        raise LeaseError("task lease is unavailable or expired")
    task.heartbeat_at = now
    task.lease_expires_at = now + timedelta(seconds=lease_seconds)
    task.state_version += 1
    task.updated_at = now
    session.flush()
    return task
