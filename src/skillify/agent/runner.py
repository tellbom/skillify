"""Provider-neutral execution of one signed endpoint task."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import replace
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Protocol

from skillify.agent.permissions import MergedPermissions

from skillify.agent.events import EventType, TaskEvent, TaskState
from skillify.agent.provider import AgentProvider, ProviderRecovery, ProviderStartSpec, TaskSpec
from skillify.tasks.protocol import TaskEnvelope
from skillify.tasks.reporting import build_task_event
from skillify.tasks.mcp_injection import McpPackageConfig, select_task_mcp
from skillify.tasks.forgejo_issue import forgejo_issue_instructions


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
        return "task.blocked"
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
        permission_resolver: Callable[[TaskEnvelope], MergedPermissions] | None = None,
        always_mcp: tuple[str, ...] = (),
    ) -> None:
        self.providers = dict(providers)
        self.start_spec = start_spec
        self.outbox = outbox
        self.mcp_catalog = dict(mcp_catalog or {})
        self.per_task_mcp = dict(per_task_mcp or {})
        self.log = log or (lambda message: None)
        self.permission_resolver = permission_resolver
        self.always_mcp = tuple(dict.fromkeys(always_mcp))
        self._active_lock = threading.Lock()
        self._active: dict[str, tuple[AgentProvider, object, object]] = {}
        self._cancelled: set[str] = set()

    def cancel(self, task_id: str) -> bool:
        """Cancel the provider session currently owned by this skillctl process."""
        with self._active_lock:
            active = self._active.get(task_id)
            if active is None:
                return False
            self._cancelled.add(task_id)
        provider, handle, session = active
        provider.cancel(handle, session)
        return True

    def run(self, envelope: TaskEnvelope, *, state_version: int) -> int:
        provider = self.providers.get(envelope.runtime)
        if provider is None:
            raise TaskRunnerError(f"provider is unavailable for runtime {envelope.runtime}")
        prompt = (
            f"Execute published workflow {envelope.workflow_id}@{envelope.workflow_version}. "
            f"Fixed inputs: {json.dumps(dict(envelope.parameters), sort_keys=True, ensure_ascii=False)}"
            f"{forgejo_issue_instructions(envelope.workflow_id, envelope.parameters)}"
        )
        if "catalog" in self.always_mcp:
            prompt += (
                "\nRuntime Skill catalog (required): before implementation, call skills.search "
                "using the Issue/task intent. If a relevant result exists, call skills.load and "
                "follow its returned SKILL.md in this run. If the task explicitly names a Skill, "
                "search and load that Skill. Do not ask the user to choose or install a Skill; "
                "continue with the best relevant result, or continue without one when search is empty."
            )
        recovery = ProviderRecovery("absent")
        recover = getattr(provider, "recover", None)
        if envelope.runtime == "shogun" and callable(recover):
            recovery = recover(envelope.task_id)
        if recovery.status == "dead":
            event_id = uuid.uuid5(
                uuid.NAMESPACE_URL, f"skillify:{envelope.task_id}:team-recovery-dead",
            ).hex
            self.outbox.enqueue(event_id, build_task_event(
                event_id=event_id,
                task_id=envelope.task_id,
                event_type="task.failed",
                occurred_at=datetime.now(timezone.utc),
                workflow_id=envelope.workflow_id,
                workflow_version=envelope.workflow_version,
                provider="shogun",
                provider_version=str(getattr(provider, "provider_version", "unknown")),
                reason_code="team-recovery-dead",
                nonce=envelope.nonce,
                state_version=state_version,
            ))
            return state_version + 1
        if recovery.status == "live":
            assert recovery.handle is not None and recovery.session is not None
            handle, session = recovery.handle, recovery.session
        else:
            start_spec = self.start_spec(envelope)
            if self.permission_resolver is not None:
                start_spec = replace(
                    start_spec, permissions=self.permission_resolver(envelope),
                )
            injection_runtime = envelope.preferred_cli if envelope.runtime == "shogun" else envelope.runtime
            requested_mcp = tuple(dict.fromkeys((*envelope.mcp_packages, *self.always_mcp)))
            plan = select_task_mcp(
                requested_mcp, self.mcp_catalog, runtime=injection_runtime or envelope.runtime,
                workspace=start_spec.workspace,
                per_task_supported=self.per_task_mcp.get(injection_runtime or envelope.runtime, True),
            )
            if plan.log:
                self.log(plan.log)
            start_spec = replace(start_spec, mcp_servers=plan.servers)
            handle = provider.start(start_spec)
            try:
                session = provider.create_session(handle, TaskSpec(envelope.task_id, prompt))
            except BaseException:
                provider.stop(handle)
                raise
        with self._active_lock:
            self._active[envelope.task_id] = (provider, handle, session)
        version = state_version
        try:
            for event in provider.stream_events(handle, session):
                with self._active_lock:
                    cancelled = envelope.task_id in self._cancelled
                if cancelled:
                    break
                blocking_question = (
                    event.type is EventType.TOOL_COMPLETED
                    and str(event.details.get("tool_name", "")).endswith("ask_question")
                )
                event_type = "task.blocked" if blocking_question else _reported_type(event)
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
                if blocking_question:
                    break
        finally:
            with self._active_lock:
                cancelled = envelope.task_id in self._cancelled
            if cancelled:
                event_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"skillify:{envelope.task_id}:{session.session_id}:task.cancelled:external",
                ).hex
                self.outbox.enqueue(event_id, build_task_event(
                    event_id=event_id,
                    task_id=envelope.task_id,
                    event_type="task.cancelled",
                    occurred_at=datetime.now(timezone.utc),
                    workflow_id=envelope.workflow_id,
                    workflow_version=envelope.workflow_version,
                    provider=handle.provider,
                    provider_version=handle.provider_version,
                    nonce=envelope.nonce,
                    state_version=version,
                ))
                version += 1
            provider.stop(handle)
            with self._active_lock:
                self._active.pop(envelope.task_id, None)
                self._cancelled.discard(envelope.task_id)
        return version
