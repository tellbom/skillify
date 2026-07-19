"""Allowlisted endpoint event payloads and idempotent outbox delivery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import requests

from skillify.agent.events import TASK_PROTOCOL_VERSION
from skillify.cli.bridge_cmd import LocalOutbox


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
EVENT_TYPES = frozenset({
    "task.received", "task.confirmed", "task.started", "test.completed",
    "artifact.created", "task.succeeded", "task.failed", "task.rejected",
    "task.cancelled", "task.rolled_back",
    "team.preparing", "team.started", "worker.started",
    "work_package.assigned", "work_package.blocked", "work_package.started",
    "work_package.completed", "review.started", "review.completed",
    "team.waiting_approval", "team.cancelling", "team.cancelled",
    "team.completed", "team.failed",
})


@dataclass(frozen=True)
class RunTestSummary:
    passed: int
    failed: int
    skipped: int = 0

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 0 for value in (self.passed, self.failed, self.skipped)):
            raise ValueError("test counts must be non-negative integers")

    def as_dict(self) -> dict[str, int]:
        return {"passed": self.passed, "failed": self.failed, "skipped": self.skipped}


@dataclass(frozen=True)
class DiffStats:
    files_changed: int
    insertions: int
    deletions: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 0 for value in (
            self.files_changed, self.insertions, self.deletions,
        )):
            raise ValueError("diff stats must be non-negative integers")

    def as_dict(self) -> dict[str, int]:
        return {
            "filesChanged": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
        }


@dataclass(frozen=True)
class ArtifactReference:
    kind: str
    artifact_id: str
    digest: str | None = None

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.kind) or not _IDENTIFIER.fullmatch(self.artifact_id):
            raise ValueError("artifact kind and id must be opaque identifiers")
        if self.digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", self.digest):
            raise ValueError("artifact digest must be sha256")

    def as_dict(self) -> dict[str, str]:
        value = {"kind": self.kind, "artifactId": self.artifact_id}
        if self.digest is not None:
            value["digest"] = self.digest
        return value


def build_task_event(
    *,
    event_id: str,
    task_id: str,
    event_type: str,
    occurred_at: datetime,
    workflow_id: str,
    workflow_version: str,
    provider: str,
    provider_version: str,
    test_summary: RunTestSummary | None = None,
    diff_stats: DiffStats | None = None,
    artifacts: tuple[ArtifactReference, ...] = (),
    reason_code: str | None = None,
    nonce: str | None = None,
    state_version: int | None = None,
    worker_id: str | None = None,
    work_package_id: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """Construct a closed payload with no free-form prompt, source, path, or secret field."""
    identifiers = (event_id, task_id, workflow_id, provider)
    if any(type(value) is not str or not _IDENTIFIER.fullmatch(value) for value in identifiers):
        raise ValueError("event identifiers are invalid")
    if event_type not in EVENT_TYPES:
        raise ValueError("event type is not reportable")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() != timezone.utc.utcoffset(occurred_at):
        raise ValueError("occurred_at must be UTC-aware")
    if not workflow_version or not provider_version:
        raise ValueError("workflow and provider versions are required")
    if reason_code is not None and not _IDENTIFIER.fullmatch(reason_code):
        raise ValueError("reason_code must be a stable identifier")
    payload: dict[str, Any] = {
        "eventId": event_id,
        "taskId": task_id,
        "eventType": event_type,
        "occurredAt": occurred_at.isoformat(),
        "taskProtocolVersion": TASK_PROTOCOL_VERSION,
        "workflow": {"id": workflow_id, "version": workflow_version},
        "provider": {"name": provider, "version": provider_version},
    }
    if test_summary is not None:
        payload["testSummary"] = test_summary.as_dict()
    if diff_stats is not None:
        payload["diffStats"] = diff_stats.as_dict()
    if artifacts:
        payload["artifacts"] = [artifact.as_dict() for artifact in artifacts]
    if reason_code is not None:
        payload["reasonCode"] = reason_code
    if nonce is not None:
        payload["nonce"] = nonce
    if state_version is not None:
        payload["stateVersion"] = state_version
    for key, value in (
        ("workerId", worker_id), ("workPackageId", work_package_id), ("stage", stage),
    ):
        if value is not None:
            if not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"{key} must be a stable identifier")
            payload[key] = value
    return payload


class EventEndpoint(Protocol):
    def send(self, payload: dict[str, Any]) -> bool: ...


class HttpEventEndpoint:
    def __init__(self, server_url: str, token: str, *, session: requests.Session | None = None) -> None:
        self.url = f"{server_url.rstrip('/')}/api/endpoint/events"
        self.token = token
        self.session = session or requests.Session()

    def send(self, payload: dict[str, Any]) -> bool:
        try:
            response = self.session.post(
                self.url,
                headers={"Authorization": f"Bearer {self.token}"},
                json=payload,
                timeout=10,
            )
            return response.status_code in {200, 201, 202, 204}
        except requests.RequestException:
            return False


class TaskEventReporter:
    def __init__(self, outbox: LocalOutbox, endpoint: EventEndpoint) -> None:
        self.outbox = outbox
        self.endpoint = endpoint

    def enqueue(self, payload: dict[str, Any]) -> bool:
        event_id = payload.get("eventId")
        if type(event_id) is not str:
            raise ValueError("event payload requires eventId")
        return self.outbox.enqueue(event_id, payload)

    def flush(self) -> int:
        delivered = 0
        for record in self.outbox.pending():
            if not self.endpoint.send(record["payload"]):
                continue
            if self.outbox.acknowledge(record["eventId"]):
                delivered += 1
        return delivered
