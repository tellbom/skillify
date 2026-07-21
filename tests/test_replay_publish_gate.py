from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from skillify.common.config import SkillifyConfig
from skillify.index.db import init_db, make_engine
from skillify.index.models import EndpointTaskEventRecord, EndpointTaskRecord, SkillIndexEntry
from skillify.packaging.pack import PackResult
from skillify.publish.publisher import ReplayGateError, _enforce_replay_gate


NOW = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)


def _task(task_id: str, version: str) -> EndpointTaskRecord:
    return EndpointTaskRecord(
        task_id=task_id, endpoint_id="endpoint-1", owner_username="jane",
        workflow_id="feature-development", workflow_version=version,
        workspace_alias="repo", inputs={}, runtime="opencode", execution_mode="single",
        state="succeeded", created_at=NOW, updated_at=NOW,
    )


def _result(tmp_path: Path) -> PackResult:
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps({
        "workflowDefinition": {
            "id": "feature-development", "replayCases": ["primary", "regression"],
        },
    }), encoding="utf-8")
    return PackResult(
        tmp_path / "x.tar.gz", tmp_path / "x.sha256", artifact, tmp_path / "x.sbom.json",
        "a" * 64, 1, 1, "demo", "workflow", "2.0.0", "", "tester", [], {},
    )


def test_release_replay_gate_reads_persisted_task_events_and_rejects_missing_case(tmp_path: Path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'index.db').as_posix()}"
    engine = make_engine(db_url); init_db(engine)
    with Session(engine) as session:
        session.add(SkillIndexEntry(
            namespace="demo", name="workflow", version="1.0.0", checksum="b" * 64,
            published_at=NOW, tags=[], governance={"workflowId": "feature-development"},
        ))
        for version in ("1.0.0", "2.0.0"):
            for case in ("primary", "regression"):
                task_id = f"task-{version}-{case}"
                session.add(_task(task_id, version))
                session.add(EndpointTaskEventRecord(
                    event_id=f"event-{version}-{case}", task_id=task_id,
                    event_type="task.succeeded", occurred_at=NOW, stage=f"replay:{case}",
                ))
        session.commit()

    result = _result(tmp_path)
    _enforce_replay_gate(SkillifyConfig(index_db_url=db_url), result)
    evaluation = json.loads(result.artifact_manifest_path.read_text(encoding="utf-8"))[
        "replayEvaluation"
    ]
    assert evaluation["status"] == "passed"
    assert evaluation["baselinePassRate"] == evaluation["candidatePassRate"] == 1.0

    with Session(engine) as session:
        session.execute(delete(EndpointTaskEventRecord).where(
            EndpointTaskEventRecord.event_id == "event-2.0.0-regression",
        ))
        session.commit()
    with pytest.raises(ReplayGateError, match="regression"):
        _enforce_replay_gate(SkillifyConfig(index_db_url=db_url), result)
