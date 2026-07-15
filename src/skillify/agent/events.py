from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

TASK_PROTOCOL_VERSION = 1
PROVIDER_CONTRACT_VERSION = 1
JsonScalar = str | int | float | bool | None
_DETAIL_KEYS = frozenset({
    "sequence", "tool_name", "tool_call_id", "exit_code", "test_count",
    "artifact_count", "reason_code", "result_state",
})


class TaskState(str, Enum):
    QUEUED = "queued"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    TASK_ACCEPTED = "task.accepted"
    PLAN_READY = "plan.ready"
    TOOL_REQUESTED = "tool.requested"
    TOOL_COMPLETED = "tool.completed"
    TEST_COMPLETED = "test.completed"
    ARTIFACT_CREATED = "artifact.created"
    TASK_BLOCKED = "task.blocked"
    TASK_FINISHED = "task.finished"


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    session_id: str
    provider: str
    provider_version: str
    task_protocol_version: int
    provider_contract_version: int
    timestamp: datetime
    type: EventType
    state: TaskState
    details: Mapping[str, JsonScalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.task_protocol_version != TASK_PROTOCOL_VERSION:
            raise ValueError("unsupported task protocol version")
        if self.provider_contract_version != PROVIDER_CONTRACT_VERSION:
            raise ValueError("unsupported provider contract version")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() != timezone.utc.utcoffset(self.timestamp):
            raise ValueError("timestamp must be UTC-aware")
        copied = dict(self.details)
        invalid = set(copied) - _DETAIL_KEYS
        if invalid or any(not isinstance(v, (str, int, float, bool, type(None))) for v in copied.values()):
            raise ValueError("invalid event detail")
        object.__setattr__(self, "details", MappingProxyType(copied))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id, "session_id": self.session_id,
            "provider": self.provider, "provider_version": self.provider_version,
            "task_protocol_version": self.task_protocol_version,
            "provider_contract_version": self.provider_contract_version,
            "timestamp": self.timestamp.isoformat(), "type": self.type.value,
            "state": self.state.value, "details": dict(self.details),
        }
