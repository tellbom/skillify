from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skillify.index.db import init_db, make_engine
from skillify.index.models import EndpointBinding, EndpointTaskRecord
from skillify.tasks.protocol import TaskEnvelope
from skillify.web.app import app
from skillify.web.auth import require_keycloak_user
from skillify.web.endpoint_auth import require_endpoint_machine


client = TestClient(app)
NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
SECRET = "development-task-signing-secret"


def _configure(monkeypatch, tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'endpoint-api.db').as_posix()}"
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", url)
    monkeypatch.setenv("SKILLIFY_ENDPOINT_TASK_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("SKILLIFY_ENDPOINT_DEVICE_SECRET", "device-secret")
    engine = make_engine(url); init_db(engine)
    with Session(engine) as session:
        session.add_all([
            EndpointBinding(
                endpoint_id="endpoint-1", owner_username="jane", label="Laptop", online=True,
                workspace_aliases=["billing"], last_seen_at=NOW,
            ),
            EndpointBinding(
                endpoint_id="endpoint-2", owner_username="bob", label="Other", online=True,
                workspace_aliases=["billing"], last_seen_at=NOW,
            ),
        ]); session.commit()
    return url


def _dispatch() -> str:
    app.dependency_overrides[require_keycloak_user] = lambda: {"preferred_username": "jane", "sub": "jane"}
    response = client.post("/api/endpoint-tasks", json={
        "endpointId": "endpoint-1", "workflowId": "evidence-bugfix",
        "workflowVersion": "1.0.0", "workspaceAlias": "billing",
        "runtime": "claude-code", "inputs": {"issueReference": "BUG-42"},
    })
    assert response.status_code == 200, response.text
    task_id = response.json()["taskId"]
    confirmed = client.post(f"/api/endpoint-tasks/{task_id}/work-packages/confirm")
    assert confirmed.status_code == 200, confirmed.text
    return task_id


def _as_endpoint(endpoint_id: str = "endpoint-1", owner: str = "jane") -> None:
    app.dependency_overrides[require_endpoint_machine] = lambda: {
        "owner": owner, "endpoint_id": endpoint_id, "identity_kind": "endpoint",
    }


def test_web_user_identity_cannot_authenticate_endpoint_routes(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    app.dependency_overrides[require_keycloak_user] = lambda: {
        "preferred_username": "jane", "sub": "jane", "endpoint_id": "endpoint-1",
    }
    try:
        response = client.get("/api/endpoint/tasks/pull", headers={"Authorization": "Bearer web-token"})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_pull_confirm_event_and_duplicate_event(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path); task_id = _dispatch(); _as_endpoint()
    try:
        pulled = client.get("/api/endpoint/tasks/pull")
        assert pulled.status_code == 200, pulled.text
        envelope = TaskEnvelope.from_dict(pulled.json()["tasks"][0])
        envelope.verify(SECRET.encode(), datetime.now(timezone.utc))
        assert envelope.task_id == task_id and envelope.runtime == "claude-code"
        assert client.get("/api/endpoint/tasks/pull").json()["tasks"][0] == envelope.to_dict()

        confirmed = client.post(
            f"/api/endpoint/tasks/{task_id}/confirm",
            json={"nonce": envelope.nonce, "stateVersion": envelope.state_version},
        )
        assert confirmed.status_code == 200 and confirmed.json()["state"] == "running"
        version = confirmed.json()["stateVersion"]
        event = {
            "eventId": "event-1", "taskId": task_id, "nonce": envelope.nonce,
            "stateVersion": version, "eventType": "test.completed",
            "occurredAt": datetime.now(timezone.utc).isoformat(),
            "testSummary": {"passed": 3, "failed": 0, "skipped": 0},
            "diffStats": {"filesChanged": 1, "insertions": 4, "deletions": 1},
        }
        accepted = client.post("/api/endpoint/events", json=event)
        assert accepted.status_code == 200 and accepted.json()["accepted"] is True
        duplicate = client.post("/api/endpoint/events", json=event)
        assert duplicate.status_code == 200 and duplicate.json()["accepted"] is False
    finally:
        app.dependency_overrides.clear()


def test_heartbeat_rejects_expired_lease_and_other_endpoint(monkeypatch, tmp_path: Path) -> None:
    url = _configure(monkeypatch, tmp_path); task_id = _dispatch(); _as_endpoint()
    try:
        envelope = TaskEnvelope.from_dict(client.get("/api/endpoint/tasks/pull").json()["tasks"][0])
        engine = make_engine(url)
        with Session(engine) as session:
            task = session.get(EndpointTaskRecord, task_id)
            task.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
        expired = client.post(
            f"/api/endpoint/tasks/{task_id}/heartbeat",
            json={"nonce": envelope.nonce, "stateVersion": envelope.state_version},
        )
        assert expired.status_code == 409
        _as_endpoint("endpoint-2", "bob")
        assert client.get("/api/endpoint/tasks/pull").status_code == 200
        wrong = client.post(
            f"/api/endpoint/tasks/{task_id}/cancel",
            json={"nonce": envelope.nonce, "stateVersion": envelope.state_version},
        )
        assert wrong.status_code == 403
    finally:
        app.dependency_overrides.clear()
