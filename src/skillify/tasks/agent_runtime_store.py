"""Durable control-plane state for programmatically hosted Agent sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from skillify.index.models import (
    AgentInteractionRecord,
    AgentRuntimeEventRecord,
    AgentWorkerRunRecord,
    ProviderSessionRecord,
)
from skillify.tasks.protocol import TaskConflictError, TaskProtocolError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def register_provider_session(
    session: Session,
    *,
    task_id: str,
    team_run_id: str | None,
    worker_id: str,
    provider: str,
    provider_session_id: str,
    runtime_instance_id: str,
    endpoint_id: str,
    workspace: str,
    work_package_id: str | None = None,
    required: bool = True,
    depends_on: list[str] | None = None,
    resume_metadata: dict | None = None,
    now: datetime | None = None,
) -> ProviderSessionRecord:
    now = now or utcnow()
    existing = session.scalar(select(ProviderSessionRecord).where(
        ProviderSessionRecord.task_id == task_id,
        ProviderSessionRecord.worker_id == worker_id,
    ))
    if existing is not None:
        identity = (
            existing.provider,
            existing.provider_session_id,
            existing.endpoint_id,
        )
        submitted = (provider, provider_session_id, endpoint_id)
        if identity != submitted:
            raise TaskConflictError("worker is already bound to another provider session")
        existing.runtime_instance_id = runtime_instance_id
        existing.resume_metadata = resume_metadata or existing.resume_metadata
        existing.status = "running"
        existing.updated_at = now
        session.flush()
        return existing
    worker = AgentWorkerRunRecord(
        worker_run_id=f"wr-{uuid4().hex}",
        task_id=task_id,
        team_run_id=team_run_id,
        worker_id=worker_id,
        work_package_id=work_package_id,
        provider=provider,
        workspace=workspace,
        status="running",
        required=required,
        depends_on=depends_on or [],
        gate_status="pending",
        gate_result={},
        created_at=now,
        updated_at=now,
        started_at=now,
    )
    record = ProviderSessionRecord(
        session_record_id=f"ps-{uuid4().hex}",
        task_id=task_id,
        team_run_id=team_run_id,
        worker_id=worker_id,
        provider=provider,
        provider_session_id=provider_session_id,
        runtime_instance_id=runtime_instance_id,
        endpoint_id=endpoint_id,
        workspace=workspace,
        status="running",
        last_event_sequence=0,
        resume_metadata=resume_metadata or {},
        created_at=now,
        updated_at=now,
    )
    session.add_all((worker, record))
    session.flush()
    return record


def record_runtime_event(
    session: Session,
    *,
    event_id: str,
    provider_session_id: str,
    sequence: int,
    event_type: str,
    payload: dict,
    occurred_at: datetime,
) -> tuple[AgentRuntimeEventRecord, bool]:
    existing = session.scalar(select(AgentRuntimeEventRecord).where(
        AgentRuntimeEventRecord.event_id == event_id,
    ))
    if existing is not None:
        return existing, False
    provider_session = session.scalar(select(ProviderSessionRecord).where(
        ProviderSessionRecord.provider_session_id == provider_session_id,
    ))
    if provider_session is None:
        raise TaskProtocolError("provider session is not registered")
    if sequence != provider_session.last_event_sequence + 1:
        raise TaskConflictError(
            f"event sequence must be {provider_session.last_event_sequence + 1}"
        )
    record = AgentRuntimeEventRecord(
        event_id=event_id,
        sequence=sequence,
        task_id=provider_session.task_id,
        team_run_id=provider_session.team_run_id,
        worker_id=provider_session.worker_id,
        provider=provider_session.provider,
        provider_session_id=provider_session_id,
        event_type=event_type,
        payload=payload,
        occurred_at=occurred_at,
    )
    provider_session.last_event_sequence = sequence
    provider_session.updated_at = occurred_at
    worker = session.scalar(select(AgentWorkerRunRecord).where(
        AgentWorkerRunRecord.task_id == provider_session.task_id,
        AgentWorkerRunRecord.worker_id == provider_session.worker_id,
    ))
    if event_type == "provider.completed":
        provider_session.status = "completed"
        provider_session.ended_at = occurred_at
        if worker is not None:
            worker.status = "ready_for_gate"
            worker.ended_at = occurred_at
            worker.updated_at = occurred_at
    elif event_type in {"provider.failed", "provider.aborted"}:
        provider_session.status = "failed" if event_type == "provider.failed" else "cancelled"
        provider_session.ended_at = occurred_at
        if worker is not None:
            worker.status = provider_session.status
            worker.ended_at = occurred_at
            worker.updated_at = occurred_at
    session.add(record)
    session.flush()
    return record, True


def request_interaction(
    session: Session,
    *,
    provider_session_id: str,
    provider_request_id: str,
    kind: str,
    title: str,
    description: str | None,
    choices: list[dict],
    allow_free_text: bool,
    expires_at: datetime | None,
    now: datetime | None = None,
) -> tuple[AgentInteractionRecord, bool]:
    provider_session = session.scalar(select(ProviderSessionRecord).where(
        ProviderSessionRecord.provider_session_id == provider_session_id,
    ))
    if provider_session is None:
        raise TaskProtocolError("provider session is not registered")
    existing = session.scalar(select(AgentInteractionRecord).where(
        AgentInteractionRecord.provider_session_id == provider_session_id,
        AgentInteractionRecord.provider_request_id == provider_request_id,
    ))
    if existing is not None:
        return existing, False
    now = now or utcnow()
    interaction = AgentInteractionRecord(
        interaction_id=f"ai-{uuid4().hex}",
        task_id=provider_session.task_id,
        team_run_id=provider_session.team_run_id,
        worker_id=provider_session.worker_id,
        provider=provider_session.provider,
        provider_session_id=provider_session_id,
        provider_request_id=provider_request_id,
        kind=kind,
        title=title,
        description=description,
        choices=choices,
        allow_free_text=allow_free_text,
        status="requested",
        response_version=0,
        created_at=now,
        expires_at=expires_at,
    )
    provider_session.status = "waiting_user"
    provider_session.pending_interaction_id = interaction.interaction_id
    provider_session.updated_at = now
    worker = session.scalar(select(AgentWorkerRunRecord).where(
        AgentWorkerRunRecord.task_id == provider_session.task_id,
        AgentWorkerRunRecord.worker_id == provider_session.worker_id,
    ))
    if worker is not None:
        worker.status = "waiting_user"
        worker.updated_at = now
    session.add(interaction)
    session.flush()
    return interaction, True


def respond_interaction(
    session: Session,
    interaction: AgentInteractionRecord,
    *,
    expected_version: int,
    choice: str | None,
    answer: str | None,
    comment: str | None,
    now: datetime | None = None,
) -> AgentInteractionRecord:
    if interaction.status != "requested":
        raise TaskConflictError("interaction is no longer awaiting a response")
    if interaction.response_version != expected_version:
        raise TaskConflictError("interaction response version changed")
    if not choice and not answer:
        raise TaskProtocolError("choice or answer is required")
    if choice and interaction.choices:
        valid = {
            str(item.get("id") or item.get("value"))
            for item in interaction.choices if isinstance(item, dict)
        }
        if choice not in valid:
            raise TaskProtocolError("choice is not offered by this interaction")
    if answer and not interaction.allow_free_text:
        raise TaskProtocolError("free-text response is not allowed")
    now = now or utcnow()
    interaction.response_choice = choice
    interaction.response_answer = answer
    interaction.response_comment = comment
    interaction.response_version += 1
    interaction.status = "responded"
    interaction.responded_at = now
    session.flush()
    return interaction


def pending_responses(
    session: Session, *, endpoint_id: str, task_id: str | None = None,
) -> list[AgentInteractionRecord]:
    query = (
        select(AgentInteractionRecord)
        .join(
            ProviderSessionRecord,
            ProviderSessionRecord.provider_session_id
            == AgentInteractionRecord.provider_session_id,
        )
        .where(
            ProviderSessionRecord.endpoint_id == endpoint_id,
            AgentInteractionRecord.status == "responded",
        )
        .order_by(AgentInteractionRecord.responded_at, AgentInteractionRecord.interaction_id)
    )
    if task_id:
        query = query.where(AgentInteractionRecord.task_id == task_id)
    return list(session.scalars(query))


def acknowledge_interaction(
    session: Session,
    interaction: AgentInteractionRecord,
    *,
    endpoint_id: str,
    target: str,
    now: datetime | None = None,
) -> AgentInteractionRecord:
    provider_session = session.scalar(select(ProviderSessionRecord).where(
        ProviderSessionRecord.provider_session_id == interaction.provider_session_id,
        ProviderSessionRecord.endpoint_id == endpoint_id,
    ))
    if provider_session is None:
        raise TaskProtocolError("interaction does not belong to this endpoint")
    now = now or utcnow()
    if target == "delivered":
        if interaction.status != "responded":
            raise TaskConflictError("only a responded interaction can be delivered")
        interaction.status = "delivered"
        interaction.delivered_at = now
    elif target == "applied":
        if interaction.status not in {"responded", "delivered"}:
            raise TaskConflictError("interaction response is not deliverable")
        interaction.status = "applied"
        interaction.delivered_at = interaction.delivered_at or now
        interaction.applied_at = now
        provider_session.status = "running"
        provider_session.pending_interaction_id = None
        provider_session.updated_at = now
        worker = session.scalar(select(AgentWorkerRunRecord).where(
            AgentWorkerRunRecord.task_id == provider_session.task_id,
            AgentWorkerRunRecord.worker_id == provider_session.worker_id,
        ))
        if worker is not None:
            worker.status = "running"
            worker.updated_at = now
    else:
        raise TaskProtocolError("unknown interaction acknowledgement")
    session.flush()
    return interaction


def list_task_runtime(session: Session, task_id: str) -> tuple[list, list, list]:
    workers = list(session.scalars(select(AgentWorkerRunRecord).where(
        AgentWorkerRunRecord.task_id == task_id,
    ).order_by(AgentWorkerRunRecord.created_at, AgentWorkerRunRecord.worker_id)))
    events = list(session.scalars(select(AgentRuntimeEventRecord).where(
        AgentRuntimeEventRecord.task_id == task_id,
    ).order_by(AgentRuntimeEventRecord.occurred_at, AgentRuntimeEventRecord.id)))
    interactions = list(session.scalars(select(AgentInteractionRecord).where(
        AgentInteractionRecord.task_id == task_id,
    ).order_by(AgentInteractionRecord.created_at, AgentInteractionRecord.interaction_id)))
    return workers, events, interactions
