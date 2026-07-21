"""Web control-plane operations for fixed-form endpoint tasks."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import false, select, update
from sqlalchemy.orm import Session

from skillify.index.models import (
    EndpointBinding, EndpointTaskEventRecord, EndpointTaskNonce, EndpointTaskRecord,
    EndpointTaskScopeGrant, EndpointTeamRecord, EndpointTeamWorkerEventRecord,
    WorkPackageRecord,
)
from skillify.codemap.visualizer import CODEMAP_WORKFLOWS
from skillify.tasks.protocol import TaskConflictError, TaskEnvelope, TaskReplayError
from skillify.tasks.work_package import WorkPackage
from skillify.tasks.work_package import validate_delegation_result
from skillify.workflows import load_bundled_workflow_pack


WORKFLOW_FORMS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "project-onboarding": (frozenset(), frozenset({"focus"})),
    "evidence-bugfix": (frozenset({"issueReference"}), frozenset({"issueReference"})),
    "feature-development": (
        frozenset({"title", "acceptanceCriteria"}),
        frozenset({"title", "acceptanceCriteria"}),
    ),
    "evidence-review": (frozenset({"changeReference"}), frozenset({"changeReference"})),
    "behavior-preserving-refactor": (frozenset({"target"}), frozenset({"target"})),
    "local-doc-search": (
        frozenset({"directoryAlias", "query", "mode"}),
        frozenset({"directoryAlias", "query", "mode"}),
    ),
    "file-processing": (
        frozenset({"inputAlias", "processor"}),
        frozenset({"inputAlias", "processor", "groupBy", "valueColumn", "operation"}),
    ),
    **{workflow_id: (frozenset(), frozenset()) for workflow_id in CODEMAP_WORKFLOWS},
}
_ALIAS = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TEAM_POLICY_KEYS = frozenset({
    "min_workers", "max_active_workers", "max_parallel_model_calls",
    "max_team_duration_minutes", "require_independent_review",
})


def _validate_team_policy(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) - _TEAM_POLICY_KEYS:
        raise ValueError("team policy contains unsupported fields")
    policy = {
        "min_workers": value.get("min_workers", 2),
        "max_active_workers": value.get("max_active_workers", 3),
        "max_parallel_model_calls": value.get("max_parallel_model_calls", 2),
        "max_team_duration_minutes": value.get("max_team_duration_minutes", 120),
        "require_independent_review": value.get("require_independent_review", True),
    }
    numeric = tuple(policy[key] for key in (
        "min_workers", "max_active_workers", "max_parallel_model_calls",
        "max_team_duration_minutes",
    ))
    if (
        any(type(item) is not int or item < 1 for item in numeric)
        or policy["min_workers"] > policy["max_active_workers"]
        or policy["max_active_workers"] > 7
        or policy["max_parallel_model_calls"] > policy["max_active_workers"]
        or type(policy["require_independent_review"]) is not bool
    ):
        raise ValueError("team policy limits are invalid")
    return policy


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
    if workflow_id in {"local-doc-search", "file-processing"}:
        from skillify.apps import load_bundled_app_contract

        load_bundled_app_contract(workflow_id).validate_input(inputs)


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
    execution_mode: str = "single",
    preferred_cli: str | None = None,
    team_policy: dict[str, Any] | None = None,
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
    if execution_mode not in {"single", "delegated", "team"}:
        raise ValueError("execution mode is unsupported")
    is_codemap = workflow_id in CODEMAP_WORKFLOWS
    is_app = workflow_id in {"local-doc-search", "file-processing"}
    delegation_mode = "adaptive" if is_codemap or is_app else load_bundled_workflow_pack(
        workflow_id,
    ).delegation.mode
    if is_codemap:
        if execution_mode != "single" or runtime not in {"codemap", "opencode"}:
            raise ValueError("Code Map actions require the fixed codemap runtime")
        runtime = "codemap"
        preferred_cli = "codemap"
    elif execution_mode == "team":
        if preferred_cli not in {"opencode", "claude-code"}:
            raise ValueError("team mode requires an approved preferred CLI")
        runtime = "shogun"
    elif runtime not in {"opencode", "claude-code"}:
        raise ValueError("runtime must be opencode or claude-code")
    policy = _validate_team_policy(dict(team_policy or {})) if execution_mode == "team" else {}
    _validate_inputs(workflow_id, inputs)
    timestamp = now or datetime.now(timezone.utc)
    task = EndpointTaskRecord(
        task_id=uuid.uuid4().hex,
        endpoint_id=endpoint_id,
        owner_username=owner,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        delegation_mode=delegation_mode,
        workspace_alias=workspace_alias,
        inputs=dict(inputs),
        runtime=runtime,
        execution_mode=execution_mode,
        collaboration_runtime="shogun" if execution_mode == "team" else None,
        preferred_cli=preferred_cli if execution_mode == "team" else runtime,
        team_policy=policy,
        state="awaiting_confirmation",
        approval_required=True,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(task)
    session.flush()
    if execution_mode == "team":
        session.add(EndpointTeamRecord(
            task_id=task.task_id, execution_mode="team", collaboration_runtime="shogun",
            preferred_cli=preferred_cli or "opencode", team_policy=policy, state="pending",
            created_at=timestamp, updated_at=timestamp,
        ))
    summary = next((value for value in inputs.values() if isinstance(value, str)), workflow_id)
    session.add(WorkPackageRecord(
        package_id=uuid.uuid4().hex, task_id=task.task_id,
        objective=(f"View Code Map for {workspace_alias}" if is_codemap else f"Complete {workflow_id}: {summary}"),
        allowed_paths=["**/*"], dependencies=[],
        access="read" if is_codemap or workflow_id == "local-doc-search" else "write",
        recommended_skills=[], recommended_mcp=[] if is_codemap else ["codegraph"],
        acceptance_commands=[], parallelizable=False, confirmed=is_codemap or is_app,
        depends_on=[], read_only=is_codemap or workflow_id == "local-doc-search", verification=[],
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
        mcp_packages=tuple(sorted({
            name for package in list_work_packages(session, task.task_id) if package.confirmed
            for name in package.recommended_mcp
        })),
        execution_mode=task.execution_mode,
        preferred_cli=task.preferred_cli,
        team_policy=task.team_policy or {},
        work_packages=tuple(_work_package_record_dict(package) for package in list_work_packages(
            session, task.task_id,
        ) if package.confirmed),
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


def confirm_app_scope(
    session: Session,
    *,
    task: EndpointTaskRecord,
    endpoint: EndpointBinding,
    purpose: str,
    aliases: list[str],
    now: datetime,
) -> EndpointTaskScopeGrant:
    """Persist an explicit endpoint confirmation without accepting filesystem paths."""
    if task.workflow_id not in {"local-doc-search", "file-processing"}:
        raise ValueError("scope confirmation is only available for Agent App tasks")
    if purpose not in {"directory-expansion", "content-upload"}:
        raise ValueError("scope confirmation purpose is unsupported")
    normalized = sorted(set(aliases))
    if (
        not normalized
        or any(not _ALIAS.fullmatch(alias) for alias in normalized)
        or not set(normalized) <= set(endpoint.workspace_aliases)
    ):
        raise ValueError("scope aliases must be registered by this endpoint")
    input_alias = task.inputs.get(
        "directoryAlias" if task.workflow_id == "local-doc-search" else "inputAlias",
    )
    if normalized != [input_alias]:
        raise ValueError("scope confirmation must exactly match the App input alias")
    if purpose == "directory-expansion" and input_alias == task.workspace_alias:
        raise ValueError("directory expansion is not required for the primary workspace alias")
    existing = session.scalar(select(EndpointTaskScopeGrant).where(
        EndpointTaskScopeGrant.task_id == task.task_id,
        EndpointTaskScopeGrant.purpose == purpose,
    ))
    if existing is not None:
        if existing.aliases != normalized or existing.endpoint_id != endpoint.endpoint_id:
            raise TaskConflictError("scope confirmation already exists with different aliases")
        return existing
    record = EndpointTaskScopeGrant(
        task_id=task.task_id, endpoint_id=endpoint.endpoint_id,
        purpose=purpose, aliases=normalized, confirmed_at=now,
    )
    session.add(record); session.flush()
    return record


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
        EndpointTaskRecord.revoked == false(),
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
    worker_id: str | None = None,
    work_package_id: str | None = None,
    stage: str | None = None,
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
        "team.started": "running", "team.completed": "succeeded",
        "team.failed": "failed", "team.cancelled": "cancelled",
        "codemap.visualization.requested": "running",
        "codemap.visualization.scan_started": "running",
        "codemap.visualization.scan_completed": "running",
        "codemap.visualization.started": "running",
        "codemap.visualization.ready": "succeeded",
        "codemap.visualization.opened": "succeeded",
        "codemap.visualization.status": "succeeded",
        "codemap.visualization.browser_blocked": "failed",
        "codemap.visualization.failed": "failed",
        "codemap.visualization.stopped": "succeeded",
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
        worker_id=worker_id, work_package_id=work_package_id, stage=stage,
    )
    session.add(record)
    if event_type.startswith(("team.", "worker.", "work_package.", "review.")):
        session.add(EndpointTeamWorkerEventRecord(
            event_id=event_id, task_id=task_id, event_type=event_type,
            worker_id=worker_id, work_package_id=work_package_id, stage=stage,
            summary=summary, occurred_at=occurred_at,
        ))
        team = session.get(EndpointTeamRecord, task_id)
        if team is not None:
            team.state = event_type
            team.updated_at = occurred_at
    session.flush()
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


def _work_package_record_dict(item: WorkPackageRecord) -> dict[str, Any]:
    return {
        "packageId": item.package_id, "taskId": item.task_id, "objective": item.objective,
        "allowedPaths": list(item.allowed_paths),
        "dependencies": list(item.dependencies), "dependsOn": list(item.depends_on or item.dependencies),
        "access": item.access, "readOnly": item.read_only or item.access == "read",
        "recommendedSkills": list(item.recommended_skills),
        "recommendedMcp": list(item.recommended_mcp),
        "acceptanceCommands": list(item.acceptance_commands),
        "verification": list(item.verification or item.acceptance_commands),
        "parallelizable": item.parallelizable, "confirmed": item.confirmed,
    }


def replace_work_packages(
    session: Session, task: EndpointTaskRecord, packages: tuple[WorkPackage, ...]
) -> list[WorkPackageRecord]:
    if task.state != "awaiting_confirmation":
        raise TaskConflictError("work packages can only be edited before endpoint confirmation")
    validate_delegation_result(task.delegation_mode, packages)
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
            depends_on=list(package.depends_on or package.dependencies),
            read_only=package.read_only or package.access == "read",
            verification=list(package.verification or package.acceptance_commands),
        )
        session.add(record); records.append(record)
    session.flush()
    return records


def confirm_work_packages(session: Session, task: EndpointTaskRecord) -> list[WorkPackageRecord]:
    packages = list_work_packages(session, task.task_id)
    if not packages:
        raise ValueError("task requires at least one work package")
    validate_delegation_result(
        task.delegation_mode,
        tuple(WorkPackage.from_dict(_work_package_record_dict(package)) for package in packages),
    )
    for package in packages:
        package.confirmed = True
    session.flush()
    return packages
