"""Official-SDK Agent runner with durable Web decisions and an explicit gate."""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from skillify.agent.host_client import AgentHostClient
from skillify.agent.permissions import MergedPermissions
from skillify.agent.provider import ProviderStartSpec
from skillify.agent.session_registry import SessionRegistry
from skillify.tasks.forgejo_issue import forgejo_issue_instructions
from skillify.tasks.mcp_injection import McpPackageConfig, select_task_mcp
from skillify.tasks.protocol import TaskEnvelope
from skillify.tasks.reporting import build_task_event


class RuntimeControlPlane(Protocol):
    def register_agent_session(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def send_agent_event(self, payload: dict[str, Any]) -> None: ...
    def request_agent_interaction(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def interaction_responses(self, task_id: str) -> list[dict[str, Any]]: ...
    def acknowledge_interaction(self, interaction_id: str, status: str) -> None: ...


class EventOutbox(Protocol):
    def enqueue(self, event_id: str, payload: dict[str, Any]) -> bool: ...


class ManagedTaskRunner:
    """Run one or more independent SDK sessions; only `_gate` reports success."""

    def __init__(
        self,
        *,
        host_factory: Callable[[], AgentHostClient],
        start_spec: Callable[[TaskEnvelope], ProviderStartSpec],
        control_plane: RuntimeControlPlane,
        outbox: EventOutbox,
        mcp_catalog: Mapping[str, McpPackageConfig],
        permission_resolver: Callable[[TaskEnvelope], MergedPermissions] | None = None,
        always_mcp: tuple[str, ...] = (),
        session_registry: SessionRegistry | None = None,
    ) -> None:
        self.host_factory = host_factory
        self.start_spec = start_spec
        self.control_plane = control_plane
        self.outbox = outbox
        self.mcp_catalog = dict(mcp_catalog)
        self.permission_resolver = permission_resolver
        self.always_mcp = always_mcp
        self.session_registry = session_registry
        self._lock = threading.Lock()
        self._active: dict[str, tuple[AgentHostClient, set[str]]] = {}
        self._cancelled: set[str] = set()

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            active = self._active.get(task_id)
            if active is None:
                return False
            host, sessions = active
            session_ids = tuple(sessions)
            self._cancelled.add(task_id)
        for session_id in session_ids:
            host.command("session.abort", providerSessionId=session_id)
        return True

    def run(self, envelope: TaskEnvelope, *, state_version: int) -> int:
        spec = self.start_spec(envelope)
        if self.permission_resolver is not None:
            spec = replace(spec, permissions=self.permission_resolver(envelope))
        base_commit = self._git(envelope, spec.workspace, "rev-parse", "HEAD").strip()
        host = self.host_factory()
        with self._lock:
            self._active[envelope.task_id] = (host, set())
        provider = envelope.preferred_cli if envelope.runtime == "shogun" else envelope.runtime
        packages = list(envelope.work_packages) or [{
            "packageId": "main",
            "objective": (
                f"Execute {envelope.workflow_id}@{envelope.workflow_version} with fixed inputs "
                f"{json.dumps(dict(envelope.parameters), ensure_ascii=False, sort_keys=True)}"
            ),
            "recommendedMcp": list(envelope.mcp_packages),
            "verification": [],
        }]
        session_to_worker: dict[str, str] = {}
        worker_workspaces: dict[str, Path] = {}
        terminal: dict[str, str] = {}
        interactions: dict[str, str] = {}
        finished = False
        try:
            pending = {
                str(package.get("packageId") or f"worker-{index + 1}"): package
                for index, package in enumerate(packages)
            }

            def start_package(worker_id: str, package: dict[str, Any]) -> None:
                registry_key = f"{envelope.task_id}:{worker_id}"
                saved = (
                    self.session_registry.load().get(registry_key)
                    if self.session_registry is not None else None
                )
                resumable = bool(
                    saved
                    and saved.get("provider") == provider
                    and Path(str(saved.get("workspace", ""))).is_dir()
                )
                worker_workspace = (
                    Path(str(saved["workspace"])) if resumable
                    else self._worker_workspace(envelope, spec, worker_id, base_commit)
                )
                worker_workspaces[worker_id] = worker_workspace
                requested_mcp = tuple(dict.fromkeys((
                    *envelope.mcp_packages,
                    *tuple(package.get("recommendedMcp") or ()),
                    *self.always_mcp,
                )))
                plan = select_task_mcp(
                    requested_mcp,
                    self.mcp_catalog,
                    runtime=str(provider),
                    workspace=worker_workspace,
                )
                prompt = (
                    f"Complete only this governed work package: {package.get('objective')}. "
                    f"Workflow: {envelope.workflow_id}@{envelope.workflow_version}. "
                    f"Fixed inputs: {json.dumps(dict(envelope.parameters), ensure_ascii=False, sort_keys=True)}"
                    f"{forgejo_issue_instructions(envelope.workflow_id, envelope.parameters)}"
                    "\nCommit the completed change in the current repository and include verification evidence."
                )
                if envelope.execution_mode == "delegated":
                    prompt += (
                        "\nUse the provider's native child-agent mechanism for a bounded review or "
                        "verification subtask; the child receives the same scoped MCP servers."
                    )
                if "catalog" in requested_mcp:
                    prompt += (
                        "\nBefore implementation call skills.search, then skills.load when relevant. "
                        "Do not ask the user to choose a Skill."
                    )
                resume_options = ({
                    "resumeSessionId": saved["providerSessionId"],
                    "initialSequence": int(saved.get("lastEventSequence", 0)),
                } if resumable else {})
                response = host.command(
                    "session.start",
                    timeout=60,
                    provider=provider,
                    taskId=envelope.task_id,
                    workerId=worker_id,
                    workspace=str(worker_workspace),
                    prompt=prompt,
                    model=spec.runtime.model,
                    mcpServers=plan.servers,
                    mcpAllowedTools=list(plan.allowed_tools),
                    **resume_options,
                )
                session_id = str(response["providerSessionId"])
                runtime_instance_id = str(response["runtimeInstanceId"])
                session_to_worker[session_id] = worker_id
                with self._lock:
                    self._active[envelope.task_id][1].add(session_id)
                self.control_plane.register_agent_session({
                    "taskId": envelope.task_id,
                    "teamRunId": envelope.task_id if envelope.execution_mode == "team" else None,
                    "workerId": worker_id,
                    "workPackageId": str(package.get("packageId") or worker_id),
                    "provider": provider,
                    "providerSessionId": session_id,
                    "runtimeInstanceId": runtime_instance_id,
                    "workspace": str(worker_workspace),
                    "required": True,
                    "dependsOn": list(package.get("dependsOn") or package.get("dependencies") or ()),
                    "resumeMetadata": {},
                })
                if self.session_registry is not None:
                    self.session_registry.put(f"{envelope.task_id}:{worker_id}", {
                        "taskId": envelope.task_id,
                        "workerId": worker_id,
                        "provider": provider,
                        "providerSessionId": session_id,
                        "runtimeInstanceId": runtime_instance_id,
                        "workspace": str(worker_workspace),
                        "lastEventSequence": int(saved.get("lastEventSequence", 0))
                        if resumable else 0,
                    })

            def schedule_ready() -> bool:
                changed = False
                with self._lock:
                    cancel_requested = envelope.task_id in self._cancelled
                if cancel_requested:
                    for worker_id in tuple(pending):
                        terminal[worker_id] = "provider.aborted"
                        pending.pop(worker_id)
                    return True
                completed = {
                    worker_id for worker_id, outcome in terminal.items()
                    if outcome == "provider.completed"
                }
                failed = set(terminal) - completed
                for worker_id, package in tuple(pending.items()):
                    dependencies = set(
                        package.get("dependsOn") or package.get("dependencies") or (),
                    )
                    if dependencies & failed:
                        terminal[worker_id] = "dependency.failed"
                        pending.pop(worker_id)
                        changed = True
                    elif dependencies <= completed:
                        start_package(worker_id, package)
                        pending.pop(worker_id)
                        changed = True
                return changed

            schedule_ready()
            if pending and not session_to_worker:
                raise RuntimeError("work package dependency graph has no runnable root")
            while len(terminal) < len(packages):
                event = host.next_event(timeout=0.25)
                if event is not None:
                    session_id = str(event.get("providerSessionId") or "")
                    if session_id in session_to_worker:
                        self._handle_event(
                            envelope, event, interactions=interactions,
                        )
                        if event["type"] in {
                            "provider.completed", "provider.failed", "provider.aborted",
                        }:
                            terminal[session_to_worker[session_id]] = str(event["type"])
                            changed = schedule_ready()
                            active_workers = set(session_to_worker.values()) - set(terminal)
                            if pending and not active_workers and not changed:
                                for blocked_worker in tuple(pending):
                                    terminal[blocked_worker] = "dependency.failed"
                                    pending.pop(blocked_worker)
                for interaction in self.control_plane.interaction_responses(envelope.task_id):
                    interaction_id = str(interaction["interactionId"])
                    if interaction_id not in interactions:
                        continue
                    response = interaction.get("response") or {}
                    host.command(
                        "interaction.respond",
                        providerSessionId=interaction["providerSessionId"],
                        providerRequestId=interaction["providerRequestId"],
                        responseVersion=response["version"],
                        choice=response.get("choice"),
                        answer=response.get("answer"),
                        comment=response.get("comment"),
                    )
                    self.control_plane.acknowledge_interaction(interaction_id, "applied")
                    interactions.pop(interaction_id, None)
                time.sleep(0.05)
            with self._lock:
                cancelled = envelope.task_id in self._cancelled
            integration_error = None
            if (
                not cancelled
                and envelope.execution_mode == "team"
                and all(value == "provider.completed" for value in terminal.values())
            ):
                integration_error = self._integrate_team(
                    envelope, spec.workspace, base_commit, worker_workspaces,
                )
            if cancelled and terminal and all(
                value in {"provider.aborted", "provider.completed"} for value in terminal.values()
            ):
                event_type = "task.cancelled"
                result = {"reason": "user-cancelled"}
                passed = False
            else:
                if integration_error:
                    passed, result = False, {
                        "reason": "integration-failed",
                        "detail": integration_error,
                    }
                else:
                    passed, result = self._gate(
                        envelope, spec.workspace, base_commit, packages, terminal,
                    )
                event_type = "gate.passed" if passed else "gate.failed"
            event_id = uuid.uuid5(
                uuid.NAMESPACE_URL, f"skillify:{envelope.task_id}:{event_type}:{base_commit}",
            ).hex
            self.outbox.enqueue(event_id, build_task_event(
                event_id=event_id,
                task_id=envelope.task_id,
                event_type=event_type,
                occurred_at=datetime.now(timezone.utc),
                workflow_id=envelope.workflow_id,
                workflow_version=envelope.workflow_version,
                provider=str(provider),
                provider_version="official-sdk",
                reason_code=None if passed else str(result["reason"]),
                nonce=envelope.nonce,
                state_version=state_version,
                summary=json.dumps(result, ensure_ascii=False)[:500],
            ))
            finished = True
            return state_version + 1
        finally:
            for session_id in session_to_worker:
                try:
                    host.command("session.close", providerSessionId=session_id)
                except Exception:
                    pass
            if self.session_registry is not None and finished:
                for worker_id in session_to_worker.values():
                    self.session_registry.remove(f"{envelope.task_id}:{worker_id}")
            if envelope.execution_mode == "team" and finished:
                for worker_workspace in worker_workspaces.values():
                    subprocess.run(
                        ["git", "-C", str(spec.workspace), "worktree", "remove", "--force",
                         str(worker_workspace)],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
            host.close()
            with self._lock:
                self._active.pop(envelope.task_id, None)
                self._cancelled.discard(envelope.task_id)

    def _handle_event(
        self,
        envelope: TaskEnvelope,
        event: dict[str, Any],
        *,
        interactions: dict[str, str],
    ) -> None:
        session_id = str(event["providerSessionId"])
        sequence = int(event["sequence"])
        event_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"skillify:{event['runtimeInstanceId']}:{session_id}:{sequence}",
        ).hex
        payload = {
            "eventId": event_id,
            "providerSessionId": session_id,
            "sequence": sequence,
            "eventType": event["type"],
            "payload": event.get("payload") or {},
            "occurredAt": event["occurredAt"],
        }
        self.control_plane.send_agent_event(payload)
        if self.session_registry is not None:
            registry_key = f"{envelope.task_id}:{event['workerId']}"
            saved = self.session_registry.load().get(registry_key)
            if saved is not None:
                saved["lastEventSequence"] = sequence
                self.session_registry.put(registry_key, saved)
        if event["type"] == "interaction.requested":
            item = event.get("payload") or {}
            response = self.control_plane.request_agent_interaction({
                "providerSessionId": session_id,
                "providerRequestId": str(item["providerRequestId"]),
                "kind": str(item.get("kind") or "permission"),
                "title": str(item.get("title") or "Agent decision"),
                "description": item.get("description"),
                "choices": item.get("choices") or [],
                "allowFreeText": bool(item.get("allowFreeText")),
            })
            interaction = response.get("interaction") or {}
            interactions[str(interaction["interactionId"])] = session_id

    def _gate(
        self,
        envelope: TaskEnvelope,
        workspace: Path,
        base_commit: str,
        packages: list[dict[str, Any]],
        terminal: dict[str, str],
    ) -> tuple[bool, dict[str, Any]]:
        if any(value != "provider.completed" for value in terminal.values()):
            return False, {"reason": "provider-failed", "sessions": terminal}
        head = self._git(envelope, workspace, "rev-parse", "HEAD").strip()
        if head == base_commit:
            return False, {"reason": "missing-commit", "baseCommit": base_commit}
        status = self._git(envelope, workspace, "status", "--porcelain")
        if status.strip():
            return False, {"reason": "uncommitted-changes"}
        for package in packages:
            for command in package.get("verification") or package.get("acceptanceCommands") or ():
                completed = subprocess.run(
                    str(command),
                    cwd=workspace,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=900,
                )
                if completed.returncode:
                    return False, {
                        "reason": "verification-failed",
                        "command": str(command),
                        "exitCode": completed.returncode,
                    }
        return True, {"reason": "passed", "baseCommit": base_commit, "headCommit": head}

    def _worker_workspace(
        self,
        envelope: TaskEnvelope,
        spec: ProviderStartSpec,
        worker_id: str,
        base_commit: str,
    ) -> Path:
        if envelope.execution_mode != "team":
            return spec.workspace
        safe_worker = re.sub(r"[^A-Za-z0-9._-]", "-", worker_id)
        path = spec.config_dir / "worktrees" / safe_worker
        path.parent.mkdir(parents=True, exist_ok=True)
        branch = f"skillify/{envelope.task_id}/{safe_worker}"
        completed = subprocess.run(
            ["git", "-C", str(spec.workspace), "worktree", "add", "-b", branch,
             str(path), base_commit],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode:
            raise RuntimeError(f"failed to create worker worktree: {completed.stderr.strip()}")
        return path

    def _integrate_team(
        self,
        envelope: TaskEnvelope,
        repository: Path,
        base_commit: str,
        worker_workspaces: dict[str, Path],
    ) -> str | None:
        for worker_id, workspace in worker_workspaces.items():
            status = self._git(envelope, workspace, "status", "--porcelain")
            if status.strip():
                return f"{worker_id} has uncommitted changes"
            head = self._git(envelope, workspace, "rev-parse", "HEAD").strip()
            if head == base_commit:
                return f"{worker_id} produced no commit"
            commits = self._git(
                envelope, workspace, "rev-list", "--reverse", f"{base_commit}..{head}",
            ).split()
            for commit in commits:
                result = subprocess.run(
                    ["git", "-C", str(repository), "cherry-pick", commit],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode:
                    subprocess.run(
                        ["git", "-C", str(repository), "cherry-pick", "--abort"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    return f"{worker_id} commit {commit} conflicted during integration"
        return None

    @staticmethod
    def _git(envelope: TaskEnvelope, workspace: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode:
            raise RuntimeError(
                f"git {' '.join(args)} failed for task {envelope.task_id}: "
                f"{completed.stderr.strip()}"
            )
        return completed.stdout
