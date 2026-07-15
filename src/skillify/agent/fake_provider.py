from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Callable, Iterator

from skillify.agent.events import EventType, TaskEvent, TaskState
from skillify.agent.provider import (
    ProviderCapability, ProviderHandle, ProviderProbe, ProviderResult,
    ProviderSession, ProviderStartSpec, TaskSpec,
)


class FakeOutcome(str, Enum):
    SUCCEED = "succeed"
    FAIL = "fail"
    BLOCK = "block"


class FakeProvider:
    def __init__(
        self,
        *,
        outcome: FakeOutcome = FakeOutcome.SUCCEED,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        self.outcome = outcome
        self.clock = clock
        self.id_factory = id_factory
        self.handles: dict[str, ProviderHandle] = {}
        self.sessions: dict[str, ProviderSession] = {}
        self.cancelled_session_ids: set[str] = set()

    @property
    def live_handle_count(self) -> int: return len(self.handles)
    @property
    def live_session_count(self) -> int: return len(self.sessions)

    def probe(self) -> ProviderProbe:
        return ProviderProbe(True, ProviderCapability("fake", "1.0.0"))

    def start(self, spec: ProviderStartSpec) -> ProviderHandle:
        handle = ProviderHandle(self.id_factory(), "fake", "1.0.0", "fake://local", 1)
        self.handles[handle.handle_id] = handle
        return handle

    def create_session(self, handle: ProviderHandle, spec: TaskSpec) -> ProviderSession:
        if handle.handle_id not in self.handles: raise ValueError("unknown handle")
        session = ProviderSession(spec.task_id, self.id_factory(), handle.handle_id)
        self.sessions[session.session_id] = session
        return session

    def _event(self, session: ProviderSession, kind: EventType, state: TaskState, sequence: int) -> TaskEvent:
        return TaskEvent(session.task_id, session.session_id, "fake", "1.0.0", 1, 1,
                         self.clock(), kind, state, {"sequence": sequence})

    def stream_events(self, handle: ProviderHandle, session: ProviderSession) -> Iterator[TaskEvent]:
        if session.session_id in self.cancelled_session_ids:
            yield self._event(session, EventType.TASK_FINISHED, TaskState.CANCELLED, 1)
            return
        if self.outcome is FakeOutcome.FAIL:
            yield self._event(session, EventType.TASK_ACCEPTED, TaskState.QUEUED, 1)
            yield self._event(session, EventType.TASK_FINISHED, TaskState.FAILED, 2)
            return
        if self.outcome is FakeOutcome.BLOCK:
            yield self._event(session, EventType.TASK_ACCEPTED, TaskState.QUEUED, 1)
            yield self._event(session, EventType.TASK_BLOCKED, TaskState.BLOCKED, 2)
            return
        sequence = [
            (EventType.TASK_ACCEPTED, TaskState.QUEUED),
            (EventType.PLAN_READY, TaskState.RUNNING),
            (EventType.TOOL_REQUESTED, TaskState.AWAITING_APPROVAL),
            (EventType.TOOL_COMPLETED, TaskState.RUNNING),
            (EventType.TEST_COMPLETED, TaskState.RUNNING),
            (EventType.ARTIFACT_CREATED, TaskState.RUNNING),
            (EventType.TASK_FINISHED, TaskState.SUCCEEDED),
        ]
        for index, (kind, state) in enumerate(sequence, 1):
            yield self._event(session, kind, state, index)

    def cancel(self, handle: ProviderHandle, session: ProviderSession) -> ProviderResult:
        self.cancelled_session_ids.add(session.session_id)
        return ProviderResult(TaskState.CANCELLED)

    def stop(self, handle: ProviderHandle) -> ProviderResult:
        self.handles.pop(handle.handle_id, None)
        stale = [key for key, value in self.sessions.items() if value.handle_id == handle.handle_id]
        for key in stale: self.sessions.pop(key, None)
        return ProviderResult(TaskState.SUCCEEDED)
