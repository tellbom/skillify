from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from skillify.index.db import init_db, make_engine
from skillify.index.models import EndpointTaskRecord
from skillify.tasks.lease import LeaseError, claim_next_task, heartbeat_task


NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)


def _session() -> Session:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return Session(engine)


def _task(task_id: str = "task-1", endpoint_id: str = "endpoint-1") -> EndpointTaskRecord:
    return EndpointTaskRecord(
        task_id=task_id, endpoint_id=endpoint_id, owner_username="jane",
        workflow_id="evidence-bugfix", workflow_version="1.0.0", workspace_alias="billing",
        inputs={"issueReference": "BUG-42"}, runtime="opencode", state="awaiting_confirmation",
        approval_required=True, created_at=NOW, updated_at=NOW,
    )


def test_claim_is_compare_and_set_and_idempotent_for_same_owner() -> None:
    session = _session(); session.add(_task()); session.commit()
    claimed = claim_next_task(session, endpoint_id="endpoint-1", lease_owner="bridge-1", now=NOW)
    assert claimed is not None and claimed.state_version == 1
    duplicate = claim_next_task(session, endpoint_id="endpoint-1", lease_owner="bridge-1", now=NOW)
    assert duplicate is not None and duplicate.task_id == claimed.task_id
    assert duplicate.state_version == 1
    assert claim_next_task(session, endpoint_id="endpoint-1", lease_owner="bridge-2", now=NOW) is None


def test_expired_lease_can_be_reclaimed_and_heartbeat_renews() -> None:
    session = _session(); session.add(_task()); session.commit()
    claim_next_task(session, endpoint_id="endpoint-1", lease_owner="bridge-1", now=NOW, lease_seconds=10)
    reclaimed = claim_next_task(
        session, endpoint_id="endpoint-1", lease_owner="bridge-2", now=NOW + timedelta(seconds=11),
    )
    assert reclaimed is not None and reclaimed.lease_owner == "bridge-2"
    renewed = heartbeat_task(
        session, task_id="task-1", endpoint_id="endpoint-1", lease_owner="bridge-2",
        now=NOW + timedelta(seconds=12),
    )
    assert renewed.state_version == 3


def test_heartbeat_rejects_wrong_endpoint_or_owner() -> None:
    session = _session(); session.add(_task()); session.commit()
    claim_next_task(session, endpoint_id="endpoint-1", lease_owner="bridge-1", now=NOW)
    with pytest.raises(LeaseError):
        heartbeat_task(
            session, task_id="task-1", endpoint_id="endpoint-2", lease_owner="bridge-1", now=NOW,
        )
    with pytest.raises(LeaseError):
        heartbeat_task(
            session, task_id="task-1", endpoint_id="endpoint-1", lease_owner="bridge-2", now=NOW,
        )
