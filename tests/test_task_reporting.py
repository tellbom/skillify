from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from skillify.cli.bridge_cmd import LocalOutbox
from skillify.tasks.reporting import (
    ArtifactReference,
    DiffStats,
    TaskEventReporter,
    RunTestSummary,
    build_task_event,
)


NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


class FakeEndpoint:
    def __init__(self, outcomes: list[bool]) -> None:
        self.outcomes = outcomes
        self.payloads: list[dict] = []

    def send(self, payload: dict) -> bool:
        self.payloads.append(payload)
        return self.outcomes.pop(0)


def _payload(event_id: str = "event-1") -> dict:
    return build_task_event(
        event_id=event_id,
        task_id="task-1",
        event_type="test.completed",
        occurred_at=NOW,
        workflow_id="evidence-bugfix",
        workflow_version="1.0.0",
        provider="opencode",
        provider_version="1.15.11",
        test_summary=RunTestSummary(passed=7, failed=0, skipped=1),
        diff_stats=DiffStats(files_changed=2, insertions=12, deletions=3),
        artifacts=(ArtifactReference("test-report", "artifact-1", "sha256:" + "a" * 64),),
    )


def test_payload_contains_only_verifiable_allowlisted_summary() -> None:
    payload = _payload()
    assert payload["testSummary"] == {"passed": 7, "failed": 0, "skipped": 1}
    assert payload["diffStats"] == {"filesChanged": 2, "insertions": 12, "deletions": 3}
    assert payload["artifacts"][0]["artifactId"] == "artifact-1"
    serialized = json.dumps(payload).casefold()
    for forbidden in ("prompt", "source_code", "secret", "workspace_path", "/users/"):
        assert forbidden not in serialized


def test_outbox_deduplicates_event_id_and_retries_failed_delivery(tmp_path: Path) -> None:
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")
    endpoint = FakeEndpoint([False, True])
    reporter = TaskEventReporter(outbox, endpoint)
    payload = _payload()

    assert reporter.enqueue(payload) is True
    assert reporter.enqueue(payload) is False
    assert reporter.flush() == 0
    assert len(outbox.pending()) == 1
    assert reporter.flush() == 1
    assert outbox.pending() == ()
    assert endpoint.payloads == [payload, payload]


def test_successful_fake_endpoint_delivers_each_event_once(tmp_path: Path) -> None:
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")
    endpoint = FakeEndpoint([True, True])
    reporter = TaskEventReporter(outbox, endpoint)
    reporter.enqueue(_payload("event-1"))
    reporter.enqueue(_payload("event-2"))

    assert reporter.flush() == 2
    assert reporter.flush() == 0
    assert [item["eventId"] for item in endpoint.payloads] == ["event-1", "event-2"]
