"""Provider-neutral contract used by the official SDK host."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Protocol


class RuntimeEventType(str, Enum):
    SESSION_STARTED = "session.started"
    MESSAGE_DELTA = "message.delta"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    INTERACTION_REQUESTED = "interaction.requested"
    INTERACTION_APPLIED = "interaction.applied"
    PROVIDER_COMPLETED = "provider.completed"
    PROVIDER_FAILED = "provider.failed"
    PROVIDER_ABORTED = "provider.aborted"
    HEARTBEAT = "provider.heartbeat"


@dataclass(frozen=True)
class RuntimeSession:
    task_id: str
    worker_id: str
    provider: str
    provider_session_id: str
    runtime_instance_id: str
    workspace: Path


@dataclass(frozen=True)
class RuntimeEvent:
    event_id: str
    sequence: int
    session: RuntimeSession
    type: RuntimeEventType
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("runtime event sequence must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("runtime event timestamp must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "eventId": self.event_id,
            "sequence": self.sequence,
            "taskId": self.session.task_id,
            "workerId": self.session.worker_id,
            "provider": self.session.provider,
            "providerSessionId": self.session.provider_session_id,
            "runtimeInstanceId": self.session.runtime_instance_id,
            "eventType": self.type.value,
            "occurredAt": self.occurred_at.astimezone(timezone.utc).isoformat(),
            "payload": self.payload,
        }


@dataclass(frozen=True)
class InteractionResponse:
    interaction_id: str
    provider_request_id: str
    response_version: int
    choice: str | None = None
    answer: str | None = None
    comment: str | None = None


class ManagedAgentProvider(Protocol):
    def start_session(self, request: dict[str, Any]) -> RuntimeSession: ...
    def send_prompt(self, session: RuntimeSession, prompt: str) -> None: ...
    def subscribe_events(self, session: RuntimeSession) -> Iterator[RuntimeEvent]: ...
    def respond_interaction(
        self, session: RuntimeSession, response: InteractionResponse,
    ) -> None: ...
    def abort_session(self, session: RuntimeSession) -> None: ...
    def get_session_state(self, session: RuntimeSession) -> dict[str, Any]: ...
    def get_session_diff(self, session: RuntimeSession) -> dict[str, Any]: ...
    def resume_session(self, metadata: dict[str, Any]) -> RuntimeSession: ...
    def close_session(self, session: RuntimeSession) -> None: ...
