from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skillify.index.db import init_db, make_engine
from skillify.index.models import EndpointBinding
from skillify.web.app import app
from skillify.web.auth import require_keycloak_user


client = TestClient(app)


def _configure(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", f"sqlite:///{db_path.as_posix()}")
    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)
    with Session(engine) as session:
        session.add_all([
            EndpointBinding(
                endpoint_id="jane-online", owner_username="jane", label="Jane laptop",
                online=True, workspace_aliases=["billing"],
                last_seen_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            ),
            EndpointBinding(
                endpoint_id="jane-offline", owner_username="jane", label="Jane desktop",
                online=False, workspace_aliases=["billing"],
                last_seen_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            ),
            EndpointBinding(
                endpoint_id="bob-online", owner_username="bob", label="Bob laptop",
                online=True, workspace_aliases=["billing"],
                last_seen_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            ),
        ])
        session.commit()
    app.dependency_overrides[require_keycloak_user] = lambda: {
        "preferred_username": "jane", "sub": "jane-id",
    }


def _task(endpoint_id: str = "jane-online", inputs: dict | None = None) -> dict:
    return {
        "endpointId": endpoint_id,
        "workflowId": "evidence-bugfix",
        "workflowVersion": "1.0.0",
        "workspaceAlias": "billing",
        "inputs": {"issueReference": "BUG-42"} if inputs is None else inputs,
    }


def test_lists_only_current_users_bound_endpoints(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    try:
        response = client.get("/api/my/endpoints")
        assert response.status_code == 200
        assert {item["endpointId"] for item in response.json()} == {
            "jane-online", "jane-offline",
        }
    finally:
        app.dependency_overrides.clear()


def test_dispatches_fixed_workflow_to_owned_online_endpoint(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    try:
        response = client.post("/api/endpoint-tasks", json=_task())
        assert response.status_code == 200, response.text
        task = response.json()
        assert task["state"] == "awaiting_confirmation"
        assert task["approvalRequired"] is True
        assert task["workflowId"] == "evidence-bugfix"
        assert task["workPackages"][0]["recommendedMcp"] == ["codegraph", "forgejo"]
        listed = client.get("/api/endpoint-tasks").json()
        assert [item["taskId"] for item in listed] == [task["taskId"]]
    finally:
        app.dependency_overrides.clear()


def test_dispatches_codemap_as_confirmed_read_only_endpoint_action(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    try:
        payload = _task()
        payload.update({
            "workflowId": "codemap.visualization.start", "runtime": "codemap", "inputs": {},
        })
        response = client.post("/api/endpoint-tasks", json=payload)
        assert response.status_code == 200, response.text
        task = response.json()
        assert task["runtime"] == "codemap"
        assert task["preferredCli"] == "codemap"
        assert task["workPackages"][0]["confirmed"] is True
        assert task["workPackages"][0]["readOnly"] is True
        assert task["workPackages"][0]["recommendedMcp"] == []
    finally:
        app.dependency_overrides.clear()


def test_rejects_other_users_endpoint_offline_endpoint_and_arbitrary_input(
    monkeypatch, tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path)
    try:
        assert client.post("/api/endpoint-tasks", json=_task("bob-online")).status_code == 403
        assert client.post("/api/endpoint-tasks", json=_task("jane-offline")).status_code == 409
        response = client.post(
            "/api/endpoint-tasks",
            json=_task(inputs={"issueReference": "BUG-42", "prompt": "run arbitrary shell"}),
        )
        assert response.status_code == 400
        assert "fixed form" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
