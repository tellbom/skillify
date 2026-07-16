"""Web control-plane operations for fixed-form endpoint tasks."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from skillify.index.models import EndpointBinding, EndpointTaskEventRecord, EndpointTaskRecord


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
        state="awaiting_confirmation",
        approval_required=True,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(task)
    session.flush()
    return task


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
