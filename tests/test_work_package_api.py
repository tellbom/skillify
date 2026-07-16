from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skillify.index.db import init_db, make_engine
from skillify.index.models import EndpointBinding
from skillify.web.app import app
from skillify.web.auth import require_keycloak_user


client = TestClient(app)


def test_user_edits_and_confirms_suggested_work_packages(monkeypatch, tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'work-package-api.db'}"
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", url)
    engine = make_engine(url); init_db(engine)
    with Session(engine) as session:
        session.add(EndpointBinding(
            endpoint_id="endpoint-1", owner_username="jane", label="Laptop", online=True,
            workspace_aliases=["billing"], last_seen_at=datetime.now(timezone.utc),
        )); session.commit()
    app.dependency_overrides[require_keycloak_user] = lambda: {
        "preferred_username": "jane", "sub": "jane",
    }
    try:
        created = client.post("/api/endpoint-tasks", json={
            "endpointId": "endpoint-1", "workflowId": "evidence-bugfix",
            "workflowVersion": "1.0.0", "workspaceAlias": "billing", "runtime": "opencode",
            "inputs": {"issueReference": "BUG-42"},
        })
        assert created.status_code == 200, created.text
        task_id = created.json()["taskId"]
        suggested = created.json()["workPackages"]
        assert len(suggested) == 1 and suggested[0]["confirmed"] is False

        edited = {**suggested[0], "objective": "Fix parser without changing public behavior", "allowedPaths": ["src/parser/**"]}
        updated = client.put(
            f"/api/endpoint-tasks/{task_id}/work-packages", json={"packages": [edited]},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["packages"][0]["allowedPaths"] == ["src/parser/**"]

        confirmed = client.post(f"/api/endpoint-tasks/{task_id}/work-packages/confirm")
        assert confirmed.status_code == 200
        assert confirmed.json()["packages"][0]["confirmed"] is True
    finally:
        app.dependency_overrides.clear()
