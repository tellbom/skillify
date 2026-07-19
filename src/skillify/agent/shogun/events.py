"""Map normalized Shogun queue transitions into Skillify's closed event schema."""

from __future__ import annotations

from datetime import datetime

from skillify.agent.events import (
    PROVIDER_CONTRACT_VERSION, TASK_PROTOCOL_VERSION, EventType, TaskEvent, TaskState,
)
from skillify.agent.shogun.contract import QueueItem
from skillify.agent.shogun.distribution import SHOGUN_VERSION


_STATUS_EVENTS: dict[tuple[str, str], tuple[EventType, TaskState]] = {
    ("command", "pending"): (EventType.TEAM_PREPARING, TaskState.QUEUED),
    ("command", "in_progress"): (EventType.TEAM_STARTED, TaskState.RUNNING),
    ("command", "done"): (EventType.TEAM_COMPLETED, TaskState.SUCCEEDED),
    ("command", "failed"): (EventType.TEAM_FAILED, TaskState.FAILED),
    ("command", "cancelled"): (EventType.TEAM_CANCELLED, TaskState.CANCELLED),
    ("task", "assigned"): (EventType.WORK_PACKAGE_ASSIGNED, TaskState.QUEUED),
    ("task", "pending_blocked"): (EventType.WORK_PACKAGE_BLOCKED, TaskState.BLOCKED),
    ("task", "blocked"): (EventType.WORK_PACKAGE_BLOCKED, TaskState.BLOCKED),
    ("task", "in_progress"): (EventType.WORK_PACKAGE_STARTED, TaskState.RUNNING),
    ("task", "done"): (EventType.WORK_PACKAGE_COMPLETED, TaskState.RUNNING),
    ("report", "done"): (EventType.REVIEW_COMPLETED, TaskState.RUNNING),
}


class TeamEventMapper:
    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], str] = {}
        self._sequence = 0

    def map(
        self,
        *,
        task_id: str,
        session_id: str,
        item: QueueItem,
        occurred_at: datetime,
    ) -> TaskEvent | None:
        identity = (item.kind, item.item_id)
        if not item.status or self._seen.get(identity) == item.status:
            return None
        self._seen[identity] = item.status
        mapped = _STATUS_EVENTS.get((item.kind, item.status))
        if mapped is None:
            return None
        event_type, state = mapped
        self._sequence += 1
        work_package_id = item.parent_id or (item.item_id if item.kind == "task" else None)
        details = {
            "sequence": self._sequence,
            "worker_id": item.worker_id,
            "work_package_id": work_package_id,
            "stage": item.status,
        }
        return TaskEvent(
            task_id=task_id, session_id=session_id, provider="shogun",
            provider_version=SHOGUN_VERSION,
            task_protocol_version=TASK_PROTOCOL_VERSION,
            provider_contract_version=PROVIDER_CONTRACT_VERSION,
            timestamp=occurred_at, type=event_type, state=state,
            details={key: value for key, value in details.items() if value is not None},
        )
