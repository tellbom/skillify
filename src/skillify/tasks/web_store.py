"""Web control-plane operations for fixed-form endpoint tasks."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from skillify.index.models import (
    EndpointBinding, EndpointTaskEventRecord, EndpointTaskNonce, EndpointTaskRecord,
    WorkPackageRecord,
)
from skillify.tasks.protocol import TaskConflictError, TaskEnvelope, TaskReplayError
from skillify.tasks.work_package import WorkPackage


WORKFLOW_FORMS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "project-onboarding": (frozenset(), frozenset({"focus"})),
    "evidence-bugfix": (frozenset({"issueReference"}), frozenset({"issueReference"})),
    "feature-development": (
        frozenset({"title", "acceptanceCriteria"}),
        frozenset({"title", "acceptanceCriteria"}),
    ),
    "evidence-review": (frozenset({"changeReference"}), frozenset({"changeReference"})),
    "behavior-preserving-refactor": (frozenset({"target"}), frozenset({"target"})),
}
_ALIAS = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _validate_inputs(workflow_id: str, inputs: dict[str, Any]) -> None:
    form = WORKFLOW_FORMS.get(workflow_id)
    if form is None:
        raise ValueError("workflow is not available for Web dispatch")
    required, allowed = form
    if set(inputs) - allowed or required - set(inputs):
        raise ValueError("workflow inputs do not match the fixed form")
    for value in inputs.values():
        if type(value) is str and (not value.strip() or len(value) > 500):
            raise ValueError("workflow text input must contain 1 to 500 characters")
        if type(value) is list and (
            not value or len(value) > 20 or
            any(type(item) is not str or not item.strip() or len(item) > 500 for item in value)
        ):
            raise ValueError("workflow list input is invalid")
        if type(value) not in {str, list}:
            raise ValueError("workflow inputs must be text or text lists")


def list_owned_endpoints(session: Session, owner: str) -> list[EndpointBinding]:
    return list(session.scalars(
        select(EndpointBinding).where(EndpointBinding.owner_username == owner)
        .order_by(EndpointBinding.label)
    ))


def dispatch_task(
    session: Session,
    *,
    owner: str,
    endpoint_id: str,
    workflow_id: str,
    workflow_version: str,
    workspace_alias: str,
    inputs: dict[str, Any],
    runtime: str = "opencode",
    now: datetime | None = None,
) -> EndpointTaskRecord:
    endpoint = session.get(EndpointBinding, endpoint_id)
    if endpoint is None or endpoint.owner_username != owner:
        raise PermissionError("endpoint is not bound to the current user")
    if not endpoint.online:
        raise RuntimeError("endpoint is offline")
    if not _ALIAS.fullmatch(workspace_alias) or workspace_alias not in endpoint.workspace_aliases:
        raise ValueError("workspace alias is not registered by this endpoint")
    if not re.fullmatch(r"\d+\.\d+\.\d+", workflow_version):
        raise ValueError("workflow version must be a published semantic version")
    if runtime not in {"opencode", "claude-code"}:
        raise ValueError("runtime must be opencode or claude-code")
    _validate_inputs(workflow_id, inputs)
    timestamp = now or datetime.now(timezone.utc)
    task = EndpointTaskRecord(
        task_id=uuid.uuid4().hex,
        endpoint_id=endpoint_id,
        owner_username=owner,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        workspace_alias=workspace_alias,
        inputs=dict(inputs),
        runtime=runtime,
        state="awaiting_confirmation",
        approval_required=True,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(task)
    session.flush()
    summary = next((value for value in inputs.values() if isinstance(value, str)), workflow_id)
    session.add(WorkPackageRecord(
        package_id=uuid.uuid4().hex, task_id=task.task_id,
        objective=f"Complete {workflow_id}: {summary}", allowed_paths=["**/*"],
        dependencies=[], access="write", recommended_skills=[], recommended_mcp=["codegraph"],
        acceptance_commands=[], parallelizable=False, confirmed=False,
    ))
    session.flush()
    return task


def issue_task_envelope(
    session: Session,
    task: EndpointTaskRecord,
    *,
    secret: bytes,
    now: datetime,
) -> TaskEnvelope:
    if task.envelope_json:
        return TaskEnvelope.from_dict(task.envelope_json)
    nonce = uuid.uuid4().hex
    if session.get(EndpointTaskNonce, nonce) is not None:
        raise TaskReplayError("task nonce has already been issued")
    expires_at = task.lease_expires_at or now + timedelta(minutes=5)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    envelope = TaskEnvelope(
        task_id=task.task_id,
        endpoint_id=task.endpoint_id,
        workflow_id=task.workflow_id,
        workflow_version=task.workflow_version,
        workspace_alias=task.workspace_alias,
        parameters=task.inputs,
        issued_at=now,
        expires_at=expires_at,
        nonce=nonce,
        runtime=task.runtime,
        state_version=task.state_version,
    ).sign(secret)
    task.envelope_json = envelope.to_dict()
    task.issued_at = now
    task.expires_at = expires_at
    session.add(EndpointTaskNonce(nonce=nonce, task_id=task.task_id, accepted_at=now))
    session.flush()
    return envelope


def verify_task_response(
    session: Session,
    *,
    task_id: str,
    endpoint_id: str,
    nonce: str,
    state_version: int,
) -> EndpointTaskRecord:
    task = session.get(EndpointTaskRecord, task_id)
    if task is None or task.endpoint_id != endpoint_id:
        raise PermissionError("task is not assigned to this endpoint")
    envelope = TaskEnvelope.from_dict(task.envelope_json or {})
    if envelope.nonce != nonce or task.revoked:
        raise TaskReplayError("task nonce is invalid or revoked")
    if task.state_version != state_version:
        raise TaskConflictError("task state_version is stale")
    return task


def transition_task(
    session: Session,
    *,
    task: EndpointTaskRecord,
    expected_state: str,
    target_state: str,
    now: datetime,
) -> EndpointTaskRecord:
    changed = session.execute(update(EndpointTaskRecord).where(
        EndpointTaskRecord.task_id == task.task_id,
        EndpointTaskRecord.state == expected_state,
        EndpointTaskRecord.state_version == task.state_version,
        EndpointTaskRecord.revoked.is_(False),
    ).values(
        state=target_state,
        state_version=EndpointTaskRecord.state_version + 1,
        updated_at=now,
    ).execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        raise TaskConflictError("task state changed concurrently")
    session.flush(); session.expire(task)
    return task


def record_task_event(
    session: Session,
    *,
    event_id: str,
    task_id: str,
    endpoint_id: str,
    nonce: str,
    state_version: int,
    event_type: str,
    occurred_at: datetime,
    summary: str | None = None,
    test_summary: dict[str, Any] | None = None,
    diff_stats: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    failure_reason: str | None = None,
) -> tuple[EndpointTaskEventRecord, bool]:
    existing = session.scalar(select(EndpointTaskEventRecord).where(
        EndpointTaskEventRecord.event_id == event_id,
    ))
    if existing is not None:
        return existing, False
    task = verify_task_response(
        session, task_id=task_id, endpoint_id=endpoint_id,
        nonce=nonce, state_version=state_version,
    )
    terminal = {
        "task.started": "running", "task.succeeded": "succeeded",
        "task.failed": "failed", "task.rejected": "rejected",
        "task.cancelled": "cancelled",
    }.get(event_type)
    task.state_version += 1
    if terminal is not None:
        task.state = terminal
    task.updated_at = occurred_at
    record = EndpointTaskEventRecord(
        event_id=event_id, task_id=task_id, event_type=event_type,
        occurred_at=occurred_at, summary=summary, test_summary=test_summary,
        diff_stats=diff_stats, artifacts=artifacts or [],
        failure_reason=failure_reason,
    )
    session.add(record); session.flush()
    return record, True


def list_owned_tasks(session: Session, owner: str) -> list[EndpointTaskRecord]:
    return list(session.scalars(
        select(EndpointTaskRecord).where(EndpointTaskRecord.owner_username == owner)
        .order_by(EndpointTaskRecord.created_at.desc())
    ))


def task_events(session: Session, task_id: str) -> list[EndpointTaskEventRecord]:
    return list(session.scalars(
        select(EndpointTaskEventRecord).where(EndpointTaskEventRecord.task_id == task_id)
        .order_by(EndpointTaskEventRecord.occurred_at, EndpointTaskEventRecord.id)
    ))


def list_work_packages(session: Session, task_id: str) -> list[WorkPackageRecord]:
    return list(session.scalars(
        select(WorkPackageRecord).where(WorkPackageRecord.task_id == task_id)
        .order_by(WorkPackageRecord.id)
    ))


def replace_work_packages(
    session: Session, task: EndpointTaskRecord, packages: tuple[WorkPackage, ...]
) -> list[WorkPackageRecord]:
    if task.state != "awaiting_confirmation":
        raise TaskConflictError("work packages can only be edited before endpoint confirmation")
    existing = list_work_packages(session, task.task_id)
    for item in existing:
        session.delete(item)
    session.flush()
    records = []
    for package in packages:
        if package.task_id != task.task_id:
            raise ValueError("work package taskId does not match route task")
        record = WorkPackageRecord(
            package_id=package.package_id, task_id=package.task_id,
            objective=package.objective, allowed_paths=list(package.allowed_paths),
            dependencies=list(package.dependencies), access=package.access,
            recommended_skills=list(package.recommended_skills),
            recommended_mcp=list(package.recommended_mcp),
            acceptance_commands=list(package.acceptance_commands),
            parallelizable=package.parallelizable, confirmed=False,
        )
        session.add(record); records.append(record)
    session.flush()
    return records


def confirm_work_packages(session: Session, task: EndpointTaskRecord) -> list[WorkPackageRecord]:
    packages = list_work_packages(session, task.task_id)
    if not packages:
        raise ValueError("task requires at least one work package")
    for package in packages:
        package.confirmed = True
    session.flush()
    return packages
