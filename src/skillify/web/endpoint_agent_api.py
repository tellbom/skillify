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
    confirm_app_scope, confirm_work_packages, issue_task_envelope, list_work_packages, record_task_event,
    replace_work_packages, transition_task, verify_task_response,
)
from skillify.tasks.work_package import WorkPackage
from skillify.web.auth import require_keycloak_user
from skillify.web.schemas import WorkPackageListIn
from skillify.web.endpoint_auth import require_endpoint_machine
from skillify.web.schemas import (
    EndpointEventIn, EndpointTaskLifecycleIn, EndpointTaskScopeConfirmationIn,
)


router = APIRouter()


def _web_owner(claims: dict) -> str:
    return str(claims.get("preferred_username") or claims.get("sub") or "")


def _owned_task(session: Session, task_id: str, owner: str) -> EndpointTaskRecord:
    task = session.get(EndpointTaskRecord, task_id)
    if task is None or task.owner_username != owner:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def _package_dict(item) -> dict:
    return {
        "packageId": item.package_id, "taskId": item.task_id, "objective": item.objective,
        "allowedPaths": item.allowed_paths, "dependencies": item.dependencies,
        "access": item.access, "recommendedSkills": item.recommended_skills,
        "recommendedMcp": item.recommended_mcp,
        "acceptanceCommands": item.acceptance_commands,
        "parallelizable": item.parallelizable, "confirmed": item.confirmed,
        "dependsOn": item.depends_on or item.dependencies,
        "readOnly": item.read_only or item.access == "read",
        "verification": item.verification or item.acceptance_commands,
    }


@router.get("/api/endpoint-tasks/{task_id}/work-packages")
def get_work_packages(task_id: str, claims: dict = Depends(require_keycloak_user)) -> dict:
    session = _session()
    try:
        _owned_task(session, task_id, _web_owner(claims))
        return {"packages": [_package_dict(item) for item in list_work_packages(session, task_id)]}
    finally:
        session.close()


@router.put("/api/endpoint-tasks/{task_id}/work-packages")
def put_work_packages(
    task_id: str, payload: WorkPackageListIn,
    claims: dict = Depends(require_keycloak_user),
) -> dict:
    session = _session()
    try:
        task = _owned_task(session, task_id, _web_owner(claims))
        packages = tuple(WorkPackage.from_dict(item.model_dump()) for item in payload.packages)
        records = replace_work_packages(session, task, packages)
        session.commit()
        return {"packages": [_package_dict(item) for item in records]}
    except (ValueError, TaskProtocolError) as exc:
        session.rollback(); raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/api/endpoint-tasks/{task_id}/work-packages/confirm")
def confirm_task_work_packages(
    task_id: str, claims: dict = Depends(require_keycloak_user),
) -> dict:
    session = _session()
    try:
        task = _owned_task(session, task_id, _web_owner(claims))
        records = confirm_work_packages(session, task)
        session.commit()
        return {"packages": [_package_dict(item) for item in records]}
    except ValueError as exc:
        session.rollback(); raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()


def _session() -> Session:
    cfg = load_config()
    if not cfg.index_db_url:
        raise HTTPException(status_code=503, detail="index_db_url not configured on this service")
    engine = make_engine(cfg.index_db_url); init_db(engine)
    return sessionmaker(bind=engine, future=True)()


def _identity(claims: dict) -> tuple[str, str]:
    endpoint_id = claims.get("endpoint_id")
    owner = claims.get("owner")
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
def pull_endpoint_task(claims: dict = Depends(require_endpoint_machine)) -> dict:
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
    claims: dict = Depends(require_endpoint_machine),
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
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    return _transition(task_id, payload, claims, "running")


@router.post("/api/endpoint/tasks/{task_id}/scope-confirmations")
def confirm_endpoint_task_scope(
    task_id: str, payload: EndpointTaskScopeConfirmationIn,
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        endpoint = _owned_binding(session, endpoint_id, owner)
        task = verify_task_response(
            session, task_id=task_id, endpoint_id=endpoint_id,
            nonce=payload.nonce, state_version=payload.stateVersion,
        )
        grant = confirm_app_scope(
            session, task=task, endpoint=endpoint, purpose=payload.purpose,
            aliases=payload.aliases, now=datetime.now(timezone.utc),
        )
        session.commit()
        return {
            "taskId": task_id, "purpose": grant.purpose,
            "aliases": grant.aliases, "confirmedAt": grant.confirmed_at,
        }
    except PermissionError as exc:
        session.rollback(); raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback(); raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TaskProtocolError as exc:
        session.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/api/endpoint/tasks/{task_id}/cancel")
def cancel_endpoint_task(
    task_id: str, payload: EndpointTaskLifecycleIn,
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    return _transition(task_id, payload, claims, "cancelled")


@router.post("/api/endpoint/events")
def endpoint_event(
    payload: EndpointEventIn,
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        _owned_binding(session, endpoint_id, owner)
        task = session.get(EndpointTaskRecord, payload.taskId)
        if task is not None and task.workflow_id in {"local-doc-search", "file-processing"}:
            from skillify.apps import load_bundled_app_contract

            results = [
                item.get("result") for item in payload.artifacts
                if isinstance(item, dict) and item.get("kind") == "app-result"
            ]
            if payload.eventType == "task.succeeded":
                if len(results) != 1:
                    raise TaskProtocolError("successful Agent App event requires one structured result")
                try:
                    load_bundled_app_contract(task.workflow_id).validate_output(results[0])
                except Exception as exc:
                    raise TaskProtocolError("Agent App result does not match its published contract") from exc
        _, created = record_task_event(
            session, event_id=payload.eventId, task_id=payload.taskId,
            endpoint_id=endpoint_id, nonce=payload.nonce, state_version=payload.stateVersion,
            event_type=payload.eventType, occurred_at=payload.occurredAt,
            summary=payload.summary, test_summary=payload.testSummary,
            diff_stats=payload.diffStats, artifacts=payload.artifacts,
            failure_reason=payload.failureReason,
            worker_id=payload.workerId, work_package_id=payload.workPackageId,
            stage=payload.stage,
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
