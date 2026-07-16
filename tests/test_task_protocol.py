from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from skillify.tasks.protocol import (
    EndpointTaskState,
    SQLiteTaskStore,
    TaskConflictError,
    TaskEnvelope,
    TaskProtocolError,
    TaskReplayError,
)


NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
SECRET = b"development-signing-secret"


def _envelope(**changes: object) -> TaskEnvelope:
    values = {
        "task_id": "task-1", "endpoint_id": "endpoint-1",
        "workflow_id": "evidence-bugfix", "workflow_version": "1.0.0",
        "workspace_alias": "billing-service", "parameters": {"issueId": "BUG-42"},
        "issued_at": NOW, "expires_at": NOW + timedelta(minutes=10), "nonce": "nonce-1",
    }
    values.update(changes)
    return TaskEnvelope(**values).sign(SECRET)


@pytest.fixture
def store() -> SQLiteTaskStore:
    value = SQLiteTaskStore(sqlite3.connect(":memory:"))
    value.create_schema()
    return value


def test_envelope_round_trip_signature_and_workspace_alias() -> None:
    envelope = _envelope()
    loaded = TaskEnvelope.from_dict(envelope.to_dict())
    loaded.verify(SECRET, NOW + timedelta(seconds=1))
    assert loaded == envelope
    assert loaded.workspace_alias == "billing-service"
    with pytest.raises(TaskProtocolError, match="workspace_alias"):
        _envelope(workspace_alias="/Users/alice/repo")


def test_envelope_rejects_expired_tampered_and_arbitrary_prompt() -> None:
    envelope = _envelope()
    with pytest.raises(TaskProtocolError, match="currently valid"):
        envelope.verify(SECRET, NOW + timedelta(minutes=11))
    with pytest.raises(TaskProtocolError, match="signature"):
        replace(envelope, workflow_version="2.0.0").verify(SECRET, NOW)
    with pytest.raises(TaskProtocolError, match="arbitrary"):
        _envelope(parameters={"prompt": "run anything"})


def test_accept_is_idempotent_for_identical_task(store: SQLiteTaskStore) -> None:
    envelope = _envelope()
    first = store.accept(envelope, secret=SECRET, now=NOW)
    second = store.accept(envelope, secret=SECRET, now=NOW)
    assert first == second
    assert second.state is EndpointTaskState.QUEUED
    assert second.version == 0


def test_accept_rejects_nonce_replay_and_task_id_conflict(store: SQLiteTaskStore) -> None:
    store.accept(_envelope(), secret=SECRET, now=NOW)
    with pytest.raises(TaskReplayError):
        store.accept(_envelope(task_id="task-2"), secret=SECRET, now=NOW)
    with pytest.raises(TaskConflictError):
        store.accept(_envelope(nonce="nonce-2", workflow_version="2.0.0"), secret=SECRET, now=NOW)


def test_compare_and_set_updates_only_expected_state(store: SQLiteTaskStore) -> None:
    store.accept(_envelope(), secret=SECRET, now=NOW)
    assert store.compare_and_set(
        "task-1", EndpointTaskState.QUEUED, EndpointTaskState.AWAITING_CONFIRMATION, now=NOW,
    )
    assert not store.compare_and_set(
        "task-1", EndpointTaskState.QUEUED, EndpointTaskState.RUNNING, now=NOW,
    )
    assert store.compare_and_set(
        "task-1", EndpointTaskState.AWAITING_CONFIRMATION, EndpointTaskState.RUNNING, now=NOW,
    )
    assert store.compare_and_set(
        "task-1", EndpointTaskState.RUNNING, EndpointTaskState.SUCCEEDED, now=NOW,
    )
    assert store.get("task-1").version == 3
    with pytest.raises(TaskProtocolError, match="invalid task transition"):
        store.compare_and_set(
            "task-1", EndpointTaskState.SUCCEEDED, EndpointTaskState.RUNNING, now=NOW,
        )


def test_revocation_is_idempotent_and_blocks_later_cas(store: SQLiteTaskStore) -> None:
    store.accept(_envelope(), secret=SECRET, now=NOW)
    assert store.revoke("task-1", now=NOW)
    assert store.revoke("task-1", now=NOW)
    task = store.get("task-1")
    assert task.revoked and task.state is EndpointTaskState.REVOKED
    assert not store.compare_and_set(
        "task-1", EndpointTaskState.QUEUED, EndpointTaskState.RUNNING, now=NOW,
    )
    assert not store.revoke("missing", now=NOW)
