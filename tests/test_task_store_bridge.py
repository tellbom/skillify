from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from skillify.index.db import init_db, make_engine
from skillify.index.models import AgentWorkerRunRecord, EndpointBinding
from skillify.tasks.agent_runtime_store import register_provider_session
from skillify.tasks.lease import claim_next_task
from skillify.tasks.protocol import TaskConflictError, TaskReplayError
from skillify.tasks.web_store import (
    confirm_work_packages, dispatch_task, issue_task_envelope, record_task_event,
    verify_task_response,
)


NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
SECRET = b"development-task-signing-secret"


def _session() -> Session:
    engine = make_engine("sqlite:///:memory:"); init_db(engine)
    session = Session(engine)
    session.add(EndpointBinding(
        endpoint_id="endpoint-1", owner_username="jane", label="Laptop", online=True,
        workspace_aliases=["billing"], last_seen_at=NOW,
    ))
    session.commit()
    return session


def _claimed(session: Session):
    task = dispatch_task(
        session, owner="jane", endpoint_id="endpoint-1", workflow_id="evidence-bugfix",
        workflow_version="1.0.0", workspace_alias="billing",
        inputs={"issueReference": "BUG-42"}, runtime="claude-code", now=NOW,
    )
    confirm_work_packages(session, task)
    session.commit()
    return claim_next_task(session, endpoint_id="endpoint-1", lease_owner="bridge-1", now=NOW)


def test_web_store_issues_one_signed_runtime_envelope() -> None:
    session = _session(); task = _claimed(session)
    envelope = issue_task_envelope(session, task, secret=SECRET, now=NOW)
    envelope.verify(SECRET, NOW)
    assert envelope.runtime == "claude-code"
    assert envelope.state_version == 1
    assert issue_task_envelope(session, task, secret=SECRET, now=NOW) == envelope


def test_response_nonce_state_version_and_event_id_are_idempotent() -> None:
    session = _session(); task = _claimed(session)
    envelope = issue_task_envelope(session, task, secret=SECRET, now=NOW)
    with pytest.raises(TaskReplayError):
        verify_task_response(
            session, task_id=task.task_id, endpoint_id="endpoint-1",
            nonce="wrong", state_version=envelope.state_version,
        )
    record, created = record_task_event(
        session, event_id="event-1", task_id=task.task_id, endpoint_id="endpoint-1",
        nonce=envelope.nonce, state_version=envelope.state_version,
        event_type="task.started", occurred_at=NOW,
    )
    assert created is True and task.state == "running"
    duplicate, created = record_task_event(
        session, event_id="event-1", task_id=task.task_id, endpoint_id="endpoint-1",
        nonce=envelope.nonce, state_version=envelope.state_version,
        event_type="task.started", occurred_at=NOW,
    )
    assert created is False and duplicate.id == record.id
    with pytest.raises(TaskConflictError):
        verify_task_response(
            session, task_id=task.task_id, endpoint_id="endpoint-1",
            nonce=envelope.nonce, state_version=envelope.state_version,
        )


def test_revoked_task_rejects_response() -> None:
    session = _session(); task = _claimed(session)
    envelope = issue_task_envelope(session, task, secret=SECRET, now=NOW)
    task.revoked = True; session.flush()
    with pytest.raises(TaskReplayError):
        verify_task_response(
            session, task_id=task.task_id, endpoint_id="endpoint-1",
            nonce=envelope.nonce, state_version=task.state_version,
        )


def test_task_failure_closes_running_worker_and_gate() -> None:
    session = _session(); task = _claimed(session)
    envelope = issue_task_envelope(session, task, secret=SECRET, now=NOW)
    register_provider_session(
        session,
        task_id=task.task_id,
        team_run_id=None,
        worker_id="worker-1",
        provider="claude-code",
        provider_session_id="session-1",
        runtime_instance_id="host-1",
        endpoint_id="endpoint-1",
        workspace="/workspace",
        now=NOW,
    )

    record_task_event(
        session,
        event_id="failure-1",
        task_id=task.task_id,
        endpoint_id="endpoint-1",
        nonce=envelope.nonce,
        state_version=envelope.state_version,
        event_type="task.failed",
        occurred_at=NOW,
        summary='{"reason":"control-plane-transport-error"}',
        failure_reason="control-plane-transport-error",
        stage="agent-interaction",
    )

    worker = session.query(AgentWorkerRunRecord).filter_by(worker_id="worker-1").one()
    assert worker.status == "failed"
    assert worker.gate_status == "failed"
    assert worker.gate_result["stage"] == "agent-interaction"
