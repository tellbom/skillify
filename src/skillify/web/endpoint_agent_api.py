"""Endpoint-initiated task pull, lifecycle and idempotent event routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from skillify.common.config import load_config
from skillify.index.db import init_db, make_engine
from skillify.index.models import EndpointBinding, EndpointTaskRecord
from skillify.tasks.lease import LeaseError, claim_next_task, heartbeat_task
from skillify.tasks.protocol import TaskConflictError, TaskProtocolError
from skillify.tasks.web_store import (
    issue_task_envelope, record_task_event, transition_task, verify_task_response,
)
from skillify.web.auth import require_keycloak_user
from skillify.web.schemas import EndpointEventIn, EndpointTaskLifecycleIn


router = APIRouter()


def _session() -> Session:
    cfg = load_config()
    if not cfg.index_db_url:
        raise HTTPException(status_code=503, detail="index_db_url not configured on this service")
    engine = make_engine(cfg.index_db_url); init_db(engine)
    return sessionmaker(bind=engine, future=True)()


def _identity(claims: dict) -> tuple[str, str]:
    endpoint_id = claims.get("endpoint_id")
    owner = claims.get("preferred_username") or claims.get("sub")
    if not endpoint_id or not owner:
        raise HTTPException(status_code=403, detail="endpoint identity claim is required")
    return str(endpoint_id), str(owner)


def _secret() -> bytes:
    value = load_config().endpoint_task_signing_secret
    if not value:
        raise HTTPException(status_code=503, detail="endpoint task signing secret is not configured")
    return value.encode("utf-8")


def _owned_binding(session: Session, endpoint_id: str, owner: str) -> EndpointBinding:
    binding = session.get(EndpointBinding, endpoint_id)
    if binding is None or binding.owner_username != owner:
        raise HTTPException(status_code=403, detail="endpoint is not bound to this identity")
    return binding


@router.get("/api/endpoint/tasks/pull")
def pull_endpoint_task(claims: dict = Depends(require_keycloak_user)) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        binding = _owned_binding(session, endpoint_id, owner)
        if not binding.online:
            raise HTTPException(status_code=409, detail="endpoint is offline")
        now = datetime.now(timezone.utc)
        task = claim_next_task(
            session, endpoint_id=endpoint_id, lease_owner=endpoint_id, now=now,
        )
        if task is None:
            return {"tasks": [], "nextCursor": None}
        envelope = issue_task_envelope(session, task, secret=_secret(), now=now)
        session.commit()
        return {"tasks": [envelope.to_dict()], "nextCursor": task.task_id}
    finally:
        session.close()


@router.post("/api/endpoint/tasks/{task_id}/heartbeat")
def heartbeat_endpoint_task(
    task_id: str, payload: EndpointTaskLifecycleIn,
    claims: dict = Depends(require_keycloak_user),
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        _owned_binding(session, endpoint_id, owner)
        verify_task_response(
            session, task_id=task_id, endpoint_id=endpoint_id,
            nonce=payload.nonce, state_version=payload.stateVersion,
        )
        task = heartbeat_task(
            session, task_id=task_id, endpoint_id=endpoint_id,
            lease_owner=endpoint_id, now=datetime.now(timezone.utc),
        )
        session.commit()
        return {"taskId": task.task_id, "state": task.state, "stateVersion": task.state_version}
    except PermissionError as exc:
        session.rollback(); raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (LeaseError, TaskProtocolError) as exc:
        session.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        session.close()


def _transition(
    task_id: str, payload: EndpointTaskLifecycleIn, claims: dict, target: str,
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        _owned_binding(session, endpoint_id, owner)
        task = verify_task_response(
            session, task_id=task_id, endpoint_id=endpoint_id,
            nonce=payload.nonce, state_version=payload.stateVersion,
        )
        if target == "running" and task.state != "awaiting_confirmation":
            raise TaskConflictError("task is not awaiting confirmation")
        if target == "cancelled" and task.state in {"succeeded", "failed", "cancelled", "rejected"}:
            raise TaskConflictError("task is already terminal")
        task = transition_task(
            session, task=task, expected_state=task.state,
            target_state=target, now=datetime.now(timezone.utc),
        )
        session.commit()
        return {"taskId": task.task_id, "state": task.state, "stateVersion": task.state_version}
    except PermissionError as exc:
        session.rollback(); raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TaskProtocolError as exc:
        session.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/api/endpoint/tasks/{task_id}/confirm")
def confirm_endpoint_task(
    task_id: str, payload: EndpointTaskLifecycleIn,
    claims: dict = Depends(require_keycloak_user),
) -> dict:
    return _transition(task_id, payload, claims, "running")


@router.post("/api/endpoint/tasks/{task_id}/cancel")
def cancel_endpoint_task(
    task_id: str, payload: EndpointTaskLifecycleIn,
    claims: dict = Depends(require_keycloak_user),
) -> dict:
    return _transition(task_id, payload, claims, "cancelled")


@router.post("/api/endpoint/events")
def endpoint_event(
    payload: EndpointEventIn,
    claims: dict = Depends(require_keycloak_user),
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        _owned_binding(session, endpoint_id, owner)
        _, created = record_task_event(
            session, event_id=payload.eventId, task_id=payload.taskId,
            endpoint_id=endpoint_id, nonce=payload.nonce, state_version=payload.stateVersion,
            event_type=payload.eventType, occurred_at=payload.occurredAt,
            summary=payload.summary, test_summary=payload.testSummary,
            diff_stats=payload.diffStats, artifacts=payload.artifacts,
            failure_reason=payload.failureReason,
        )
        task = session.get(EndpointTaskRecord, payload.taskId)
        session.commit()
        return {"accepted": created, "stateVersion": task.state_version}
    except PermissionError as exc:
        session.rollback(); raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TaskProtocolError as exc:
        session.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        session.close()
