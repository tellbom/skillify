"""Endpoint-initiated task pull, lifecycle and idempotent event routes."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

from skillify.common.config import load_config
from skillify.index.db import init_db, make_engine
from skillify.index.models import (
    AgentInteractionRecord, EndpointBinding, EndpointTaskRecord, ProviderSessionRecord,
)
from skillify.tasks.agent_runtime_store import (
    acknowledge_interaction, list_task_runtime, pending_responses,
    record_runtime_event, register_provider_session, request_interaction,
    respond_interaction,
)
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
    AgentInteractionAckIn, AgentInteractionRequestIn, AgentInteractionResponseIn,
    AgentRuntimeEventIn, EndpointEventIn, EndpointTaskLifecycleIn,
    EndpointTaskScopeConfirmationIn, ProviderSessionIn,
)
from skillify.web import service


router = APIRouter()


@router.get("/api/endpoint/catalog/skills")
def search_endpoint_catalog(
    q: str = Query(min_length=1),
    limit: int = Query(default=5, ge=1, le=20),
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    """Expose the existing community index to an authenticated endpoint runtime."""
    _, owner = _identity(claims)
    session = _session()
    try:
        items, total = service.list_skills(
            session, q, sort="updated", page=1, page_size=limit,
        )
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
        }
    finally:
        session.close()


@router.get("/api/endpoint/catalog/skills/{namespace}/{name}")
def load_endpoint_catalog_skill(
    namespace: str,
    name: str,
    version: str | None = Query(default=None),
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    """Return one published Skill, including SKILL.md, for the current Agent context."""
    _, owner = _identity(claims)
    cfg = load_config()
    session = _session()
    try:
        detail = service.get_skill_detail(
            session, cfg, namespace, name, version=version, username=owner,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail=f"{namespace}/{name} not found in index")
        return detail.model_dump(mode="json")
    finally:
        session.close()


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


def _interaction_dict(item: AgentInteractionRecord) -> dict:
    return {
        "interactionId": item.interaction_id,
        "taskId": item.task_id,
        "teamRunId": item.team_run_id,
        "workerId": item.worker_id,
        "provider": item.provider,
        "providerSessionId": item.provider_session_id,
        "providerRequestId": item.provider_request_id,
        "kind": item.kind,
        "title": item.title,
        "description": item.description,
        "choices": item.choices,
        "allowFreeText": item.allow_free_text,
        "status": item.status,
        "response": {
            "choice": item.response_choice,
            "answer": item.response_answer,
            "comment": item.response_comment,
            "version": item.response_version,
        },
        "createdAt": item.created_at,
        "expiresAt": item.expires_at,
        "respondedAt": item.responded_at,
        "deliveredAt": item.delivered_at,
        "appliedAt": item.applied_at,
    }


def _provider_session_for_endpoint(
    session: Session, provider_session_id: str, endpoint_id: str,
) -> ProviderSessionRecord:
    record = session.query(ProviderSessionRecord).filter_by(
        provider_session_id=provider_session_id, endpoint_id=endpoint_id,
    ).one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="provider session not found")
    return record


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
        if target == "running" and task.state == "running":
            return {"taskId": task.task_id, "state": task.state, "stateVersion": task.state_version}
        if target == "running" and task.state != "awaiting_confirmation":
            raise TaskConflictError("task is not awaiting confirmation")
        if target == "cancelled" and task.state in {
            "succeeded", "failed", "blocked", "cancelled", "rejected",
        }:
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


@router.post("/api/endpoint-tasks/{task_id}/cancel")
def request_endpoint_task_cancel(
    task_id: str, claims: dict = Depends(require_keycloak_user),
) -> dict:
    """Record a user request; only skillctl is allowed to stop a running provider."""
    session = _session()
    try:
        task = _owned_task(session, task_id, _web_owner(claims))
        if task.state in {"cancelled", "cancelling"}:
            return {"taskId": task.task_id, "state": task.state, "stateVersion": task.state_version}
        if task.state in {"succeeded", "failed", "blocked", "rejected", "revoked"}:
            raise HTTPException(status_code=409, detail="task is already terminal")
        if task.state in {"queued", "awaiting_confirmation"}:
            transition_task(
                session, task=task, expected_state=task.state, target_state="cancelled",
                now=datetime.now(timezone.utc),
            )
        elif task.state == "running":
            # Keep state_version stable: already-buffered endpoint events retain their order.
            task.state = "cancelling"
            task.updated_at = datetime.now(timezone.utc)
            session.flush()
        else:
            raise HTTPException(status_code=409, detail="task cannot be cancelled in its current state")
        session.commit()
        return {"taskId": task.task_id, "state": task.state, "stateVersion": task.state_version}
    finally:
        session.close()


@router.get("/api/endpoint/tasks/{task_id}/cancellation")
def endpoint_task_cancellation(
    task_id: str, nonce: str = Query(min_length=1),
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        _owned_binding(session, endpoint_id, owner)
        task = session.get(EndpointTaskRecord, task_id)
        if task is None or task.endpoint_id != endpoint_id:
            raise HTTPException(status_code=404, detail="task not found")
        envelope = task.envelope_json or {}
        if envelope.get("nonce") != nonce or task.revoked:
            raise HTTPException(status_code=409, detail="task nonce is invalid or revoked")
        return {
            "taskId": task.task_id,
            "cancelRequested": task.state == "cancelling",
            "state": task.state,
            "stateVersion": task.state_version,
        }
    finally:
        session.close()


@router.post("/api/endpoint/tasks/{task_id}/cancel")
def cancel_endpoint_task(
    task_id: str, payload: EndpointTaskLifecycleIn,
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    return _transition(task_id, payload, claims, "cancelled")


@router.post("/api/endpoint/agent-sessions")
def register_endpoint_agent_session(
    payload: ProviderSessionIn,
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        _owned_binding(session, endpoint_id, owner)
        task = session.get(EndpointTaskRecord, payload.taskId)
        if task is None or task.endpoint_id != endpoint_id:
            raise HTTPException(status_code=404, detail="task not found")
        record = register_provider_session(
            session,
            task_id=payload.taskId,
            team_run_id=payload.teamRunId,
            worker_id=payload.workerId,
            work_package_id=payload.workPackageId,
            provider=payload.provider,
            provider_session_id=payload.providerSessionId,
            runtime_instance_id=payload.runtimeInstanceId,
            endpoint_id=endpoint_id,
            workspace=payload.workspace,
            required=payload.required,
            depends_on=payload.dependsOn,
            resume_metadata=payload.resumeMetadata,
        )
        session.commit()
        return {
            "sessionRecordId": record.session_record_id,
            "providerSessionId": record.provider_session_id,
            "status": record.status,
            "lastEventSequence": record.last_event_sequence,
        }
    except (TaskConflictError, TaskProtocolError) as exc:
        session.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/api/endpoint/agent-events")
def post_endpoint_agent_event(
    payload: AgentRuntimeEventIn,
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        _owned_binding(session, endpoint_id, owner)
        _provider_session_for_endpoint(session, payload.providerSessionId, endpoint_id)
        record, created = record_runtime_event(
            session,
            event_id=payload.eventId,
            provider_session_id=payload.providerSessionId,
            sequence=payload.sequence,
            event_type=payload.eventType,
            payload=payload.payload,
            occurred_at=payload.occurredAt,
        )
        session.commit()
        return {"accepted": created, "sequence": record.sequence}
    except (TaskConflictError, TaskProtocolError) as exc:
        session.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/api/endpoint/agent-interactions")
def post_endpoint_agent_interaction(
    payload: AgentInteractionRequestIn,
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        _owned_binding(session, endpoint_id, owner)
        _provider_session_for_endpoint(session, payload.providerSessionId, endpoint_id)
        interaction, created = request_interaction(
            session,
            provider_session_id=payload.providerSessionId,
            provider_request_id=payload.providerRequestId,
            kind=payload.kind,
            title=payload.title,
            description=payload.description,
            choices=payload.choices,
            allow_free_text=payload.allowFreeText,
            expires_at=payload.expiresAt,
        )
        session.commit()
        return {"accepted": created, "interaction": _interaction_dict(interaction)}
    except (TaskConflictError, TaskProtocolError) as exc:
        session.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/api/endpoint/agent-interactions/responses")
def pull_endpoint_agent_interactions(
    task_id: str | None = Query(default=None, alias="taskId"),
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        _owned_binding(session, endpoint_id, owner)
        return {
            "interactions": [
                _interaction_dict(item)
                for item in pending_responses(
                    session, endpoint_id=endpoint_id, task_id=task_id,
                )
            ],
        }
    finally:
        session.close()


@router.post("/api/endpoint/agent-interactions/{interaction_id}/ack")
def acknowledge_endpoint_agent_interaction(
    interaction_id: str,
    payload: AgentInteractionAckIn,
    claims: dict = Depends(require_endpoint_machine),
) -> dict:
    endpoint_id, owner = _identity(claims); session = _session()
    try:
        _owned_binding(session, endpoint_id, owner)
        interaction = session.get(AgentInteractionRecord, interaction_id)
        if interaction is None:
            raise HTTPException(status_code=404, detail="interaction not found")
        acknowledge_interaction(
            session, interaction, endpoint_id=endpoint_id, target=payload.status,
        )
        session.commit()
        return {"interaction": _interaction_dict(interaction)}
    except (TaskConflictError, TaskProtocolError) as exc:
        session.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/api/endpoint-tasks/{task_id}/agent-runtime")
def get_task_agent_runtime(
    task_id: str,
    claims: dict = Depends(require_keycloak_user),
) -> dict:
    session = _session()
    try:
        _owned_task(session, task_id, _web_owner(claims))
        workers, events, interactions = list_task_runtime(session, task_id)
        return {
            "workers": [{
                "workerRunId": item.worker_run_id,
                "workerId": item.worker_id,
                "teamRunId": item.team_run_id,
                "workPackageId": item.work_package_id,
                "provider": item.provider,
                "workspace": item.workspace,
                "status": item.status,
                "required": item.required,
                "dependsOn": item.depends_on,
                "gateStatus": item.gate_status,
                "gateResult": item.gate_result,
                "startedAt": item.started_at,
                "endedAt": item.ended_at,
            } for item in workers],
            "events": [{
                "eventId": item.event_id,
                "sequence": item.sequence,
                "workerId": item.worker_id,
                "provider": item.provider,
                "providerSessionId": item.provider_session_id,
                "eventType": item.event_type,
                "payload": item.payload,
                "occurredAt": item.occurred_at,
            } for item in events],
            "interactions": [_interaction_dict(item) for item in interactions],
        }
    finally:
        session.close()


@router.get("/api/endpoint-tasks/{task_id}/agent-runtime/stream")
def stream_task_agent_runtime(
    task_id: str,
    claims: dict = Depends(require_keycloak_user),
) -> StreamingResponse:
    owner = _web_owner(claims)
    session = _session()
    try:
        _owned_task(session, task_id, owner)
    finally:
        session.close()

    def events():
        previous = ""
        while True:
            current = _session()
            try:
                task = _owned_task(current, task_id, owner)
                workers, runtime_events, interactions = list_task_runtime(current, task_id)
                snapshot = {
                    "taskId": task_id,
                    "state": task.state,
                    "workers": [{
                        "workerId": item.worker_id,
                        "status": item.status,
                        "gateStatus": item.gate_status,
                    } for item in workers],
                    "lastEventId": runtime_events[-1].event_id if runtime_events else None,
                    "interactions": [{
                        "interactionId": item.interaction_id,
                        "status": item.status,
                        "responseVersion": item.response_version,
                    } for item in interactions],
                }
            finally:
                current.close()
            encoded = json.dumps(snapshot, ensure_ascii=False, default=str)
            if encoded != previous:
                yield f"event: runtime.snapshot\ndata: {encoded}\n\n"
                previous = encoded
            else:
                yield ": heartbeat\n\n"
            if snapshot["state"] in {"succeeded", "failed", "cancelled", "rejected"}:
                return
            time.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/endpoint-tasks/{task_id}/agent-interactions/{interaction_id}/respond")
def respond_task_agent_interaction(
    task_id: str,
    interaction_id: str,
    payload: AgentInteractionResponseIn,
    claims: dict = Depends(require_keycloak_user),
) -> dict:
    session = _session()
    try:
        _owned_task(session, task_id, _web_owner(claims))
        interaction = session.get(AgentInteractionRecord, interaction_id)
        if interaction is None or interaction.task_id != task_id:
            raise HTTPException(status_code=404, detail="interaction not found")
        respond_interaction(
            session,
            interaction,
            expected_version=payload.responseVersion,
            choice=payload.choice,
            answer=payload.answer,
            comment=payload.comment,
        )
        session.commit()
        return {"interaction": _interaction_dict(interaction)}
    except TaskProtocolError as exc:
        session.rollback(); raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TaskConflictError as exc:
        session.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        session.close()


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
            failure_reason=payload.failureReason or payload.reasonCode,
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
