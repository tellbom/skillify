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
}


class TeamEventMapper:
    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], str] = {}
        self._started_workers: set[str] = set()
        self._sequence = 0

    def _event(
        self,
        *,
        task_id: str,
        session_id: str,
        item: QueueItem,
        occurred_at: datetime,
        event_type: EventType,
        state: TaskState,
    ) -> TaskEvent:
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

    def map_all(
        self,
        *,
        task_id: str,
        session_id: str,
        item: QueueItem,
        occurred_at: datetime,
    ) -> tuple[TaskEvent, ...]:
        identity = (item.kind, item.item_id)
        if not item.status or self._seen.get(identity) == item.status:
            return ()
        self._seen[identity] = item.status
        if item.kind == "report" and item.status == "done":
            mapped = (
                (EventType.REVIEW_COMPLETED, TaskState.RUNNING)
                if item.worker_id == "gunshi" else None
            )
        else:
            mapped = _STATUS_EVENTS.get((item.kind, item.status))
        if mapped is None:
            return ()
        event_type, state = mapped
        if item.worker_id == "gunshi":
            if item.kind == "task" and item.status in {"assigned", "in_progress"}:
                event_type, state = EventType.REVIEW_STARTED, TaskState.RUNNING
        events = []
        if item.kind == "task" and item.worker_id and item.worker_id not in self._started_workers:
            self._started_workers.add(item.worker_id)
            events.append(self._event(
                task_id=task_id, session_id=session_id, item=item, occurred_at=occurred_at,
                event_type=EventType.WORKER_STARTED, state=TaskState.RUNNING,
            ))
        events.append(self._event(
            task_id=task_id, session_id=session_id, item=item, occurred_at=occurred_at,
            event_type=event_type, state=state,
        ))
        return tuple(events)

    def map(
        self, *, task_id: str, session_id: str, item: QueueItem, occurred_at: datetime,
    ) -> TaskEvent | None:
        events = self.map_all(
            task_id=task_id, session_id=session_id, item=item, occurred_at=occurred_at,
        )
        return events[-1] if events else None
