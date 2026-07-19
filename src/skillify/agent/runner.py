"""Provider-neutral execution of one signed endpoint task."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from collections.abc import Callable, Mapping
from typing import Protocol

from skillify.agent.events import EventType, TaskEvent, TaskState
from skillify.agent.provider import AgentProvider, ProviderStartSpec, TaskSpec
from skillify.tasks.protocol import TaskEnvelope
from skillify.tasks.reporting import build_task_event
from skillify.tasks.mcp_injection import McpPackageConfig, select_task_mcp


class TaskRunnerError(RuntimeError):
    pass


class EventOutbox(Protocol):
    def enqueue(self, event_id: str, payload: dict) -> bool: ...


def _reported_type(event: TaskEvent) -> str | None:
    if event.type.value.startswith(("team.", "worker.", "work_package.", "review.")):
        return event.type.value
    if event.type is EventType.TASK_ACCEPTED:
        return "task.started"
    if event.type is EventType.TEST_COMPLETED:
        return "test.completed"
    if event.type is EventType.ARTIFACT_CREATED:
        return "artifact.created"
    if event.type is EventType.TASK_FINISHED:
        return {
            TaskState.SUCCEEDED: "task.succeeded",
            TaskState.CANCELLED: "task.cancelled",
        }.get(event.state, "task.failed")
    if event.type is EventType.TASK_BLOCKED:
        return "task.failed"
    return None


class TaskRunner:
    def __init__(
        self,
        providers: Mapping[str, AgentProvider],
        start_spec: Callable[[TaskEnvelope], ProviderStartSpec],
        outbox: EventOutbox,
        mcp_catalog: Mapping[str, McpPackageConfig] | None = None,
        per_task_mcp: Mapping[str, bool] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.providers = dict(providers)
        self.start_spec = start_spec
        self.outbox = outbox
        self.mcp_catalog = dict(mcp_catalog or {})
        self.per_task_mcp = dict(per_task_mcp or {})
        self.log = log or (lambda message: None)

    def run(self, envelope: TaskEnvelope, *, state_version: int) -> int:
        provider = self.providers.get(envelope.runtime)
        if provider is None:
            raise TaskRunnerError(f"provider is unavailable for runtime {envelope.runtime}")
        prompt = (
            f"Execute published workflow {envelope.workflow_id}@{envelope.workflow_version}. "
            f"Fixed inputs: {json.dumps(dict(envelope.parameters), sort_keys=True, ensure_ascii=False)}"
        )
        start_spec = self.start_spec(envelope)
        injection_runtime = envelope.preferred_cli if envelope.runtime == "shogun" else envelope.runtime
        plan = select_task_mcp(
            envelope.mcp_packages, self.mcp_catalog, runtime=injection_runtime or envelope.runtime,
            workspace=start_spec.workspace,
            per_task_supported=self.per_task_mcp.get(injection_runtime or envelope.runtime, True),
        )
        if plan.log:
            self.log(plan.log)
        start_spec = replace(start_spec, mcp_servers=plan.servers)
        handle = provider.start(start_spec)
        session = provider.create_session(handle, TaskSpec(envelope.task_id, prompt))
        version = state_version
        try:
            for event in provider.stream_events(handle, session):
                event_type = _reported_type(event)
                if event_type is None:
                    continue
                sequence = event.details.get("sequence", 0)
                event_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"skillify:{envelope.task_id}:{session.session_id}:{event_type}:{sequence}",
                ).hex
                payload = build_task_event(
                    event_id=event_id,
                    task_id=envelope.task_id,
                    event_type=event_type,
                    occurred_at=event.timestamp,
                    workflow_id=envelope.workflow_id,
                    workflow_version=envelope.workflow_version,
                    provider=event.provider,
                    provider_version=event.provider_version,
                    reason_code=str(event.details["reason_code"]) if event.details.get("reason_code") else None,
                    nonce=envelope.nonce,
                    state_version=version,
                    worker_id=str(event.details["worker_id"]) if event.details.get("worker_id") else None,
                    work_package_id=(
                        str(event.details["work_package_id"])
                        if event.details.get("work_package_id") else None
                    ),
                    stage=str(event.details["stage"]) if event.details.get("stage") else None,
                )
                self.outbox.enqueue(event_id, payload)
                version += 1
        finally:
            provider.stop(handle)
        return version
