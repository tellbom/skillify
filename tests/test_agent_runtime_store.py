from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from skillify.index.db import init_db, make_engine
from skillify.index.models import AgentWorkerRunRecord
from skillify.tasks.agent_runtime_store import (
    acknowledge_interaction,
    pending_responses,
    record_runtime_event,
    register_provider_session,
    request_interaction,
    respond_interaction,
)
from skillify.tasks.protocol import TaskConflictError, TaskProtocolError


NOW = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)


def _session() -> Session:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return Session(engine)


def _register(session: Session, worker: str, native_session: str):
    return register_provider_session(
        session,
        task_id="task-1",
        team_run_id="team-1",
        worker_id=worker,
        provider="claude-code",
        provider_session_id=native_session,
        runtime_instance_id="host-1",
        endpoint_id="endpoint-1",
        workspace="/workspace",
        now=NOW,
    )


def test_runtime_events_are_idempotent_and_strictly_monotonic() -> None:
    session = _session()
    provider_session = _register(session, "worker-1", "session-1")
    event, created = record_runtime_event(
        session,
        event_id="event-1",
        provider_session_id="session-1",
        sequence=1,
        event_type="session.started",
        payload={"mcpServers": ["forgejo"]},
        occurred_at=NOW,
    )
    assert created and event.sequence == 1
    duplicate, created = record_runtime_event(
        session,
        event_id="event-1",
        provider_session_id="session-1",
        sequence=1,
        event_type="session.started",
        payload={"mcpServers": ["forgejo"]},
        occurred_at=NOW,
    )
    assert not created and duplicate.id == event.id
    with pytest.raises(TaskConflictError, match="must be 2"):
        record_runtime_event(
            session,
            event_id="event-3",
            provider_session_id="session-1",
            sequence=3,
            event_type="message.delta",
            payload={},
            occurred_at=NOW,
        )
    assert provider_session.last_event_sequence == 1


def test_one_waiting_worker_does_not_block_sibling_and_response_returns_to_same_session() -> None:
    session = _session()
    _register(session, "worker-1", "session-1")
    _register(session, "worker-2", "session-2")
    interaction, created = request_interaction(
        session,
        provider_session_id="session-1",
        provider_request_id="permission-7",
        kind="permission",
        title="Allow write?",
        description="Write one governed file",
        choices=[{"id": "allow"}, {"id": "deny"}],
        allow_free_text=False,
        expires_at=NOW + timedelta(minutes=10),
        now=NOW,
    )
    assert created and interaction.status == "requested"
    workers = {
        item.worker_id: item.status
        for item in session.query(AgentWorkerRunRecord).all()
    }
    assert workers == {"worker-1": "waiting_user", "worker-2": "running"}

    respond_interaction(
        session,
        interaction,
        expected_version=0,
        choice="allow",
        answer=None,
        comment=None,
        now=NOW,
    )
    assert pending_responses(session, endpoint_id="endpoint-1") == [interaction]
    assert pending_responses(session, endpoint_id="another-endpoint") == []
    with pytest.raises(TaskConflictError):
        respond_interaction(
            session,
            interaction,
            expected_version=0,
            choice="deny",
            answer=None,
            comment=None,
        )
    acknowledge_interaction(
        session,
        interaction,
        endpoint_id="endpoint-1",
        target="applied",
        now=NOW,
    )
    assert interaction.status == "applied"
    assert session.query(AgentWorkerRunRecord).filter_by(
        worker_id="worker-1",
    ).one().status == "running"


def test_interaction_rejects_unoffered_or_free_text_response() -> None:
    session = _session()
    _register(session, "worker-1", "session-1")
    interaction, _ = request_interaction(
        session,
        provider_session_id="session-1",
        provider_request_id="permission-8",
        kind="permission",
        title="Allow?",
        description=None,
        choices=[{"id": "allow"}],
        allow_free_text=False,
        expires_at=None,
        now=NOW,
    )
    with pytest.raises(TaskProtocolError, match="not offered"):
        respond_interaction(
            session, interaction, expected_version=0,
            choice="always", answer=None, comment=None,
        )
    with pytest.raises(TaskProtocolError, match="not allowed"):
        respond_interaction(
            session, interaction, expected_version=0,
            choice=None, answer="yes", comment=None,
        )
