"""Small declarative contract and serial executor for local workflow packs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from skillify.agent.events import TaskState
from skillify.agent.provider import AgentProvider, ProviderStartSpec, TaskSpec
from skillify.validator import validate_skill_dir


@dataclass(frozen=True)
class WorkflowRole:
    id: str
    prompt: str
    output: str
    requires_evidence: bool = False


@dataclass(frozen=True)
class WorkflowGate:
    id: str
    before_role: str
    required_by_default: bool


@dataclass(frozen=True)
class WorkflowPack:
    path: Path
    id: str
    mode: str
    roles: tuple[WorkflowRole, ...]
    artifacts: tuple[str, ...]
    gates: tuple[WorkflowGate, ...]


@dataclass(frozen=True)
class WorkflowExecution:
    workflow_id: str
    completed_roles: tuple[str, ...]
    role_states: tuple[TaskState, ...]
    artifacts: tuple[str, ...]


def _safe_relative(value: object) -> str:
    if type(value) is not str:
        raise ValueError("workflow artifact paths must be strings")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("workflow artifact paths must be normalized relative paths")
    return value


def _mapping(value: object, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"workflow {field} must be an object")
    return value


def load_workflow_pack(path: Path) -> WorkflowPack:
    """Validate the Skillify artifact plus its serial workflow definition."""
    root = Path(path)
    validation = validate_skill_dir(root)
    if not validation.ok:
        messages = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise ValueError(f"invalid Skillify pack: {messages}")
    value = yaml.safe_load((root / "workflow.yaml").read_text(encoding="utf-8"))
    document = _mapping(value, "definition")
    if document.get("workflowVersion") != 1 or document.get("execution") != "serial":
        raise ValueError("workflow must use version 1 serial execution")
    workflow_id = document.get("id")
    mode = document.get("mode")
    if type(workflow_id) is not str or not workflow_id or mode not in {"read-only", "workspace-write"}:
        raise ValueError("workflow id and supported mode are required")

    role_values = document.get("roles")
    if type(role_values) is not list or not role_values:
        raise ValueError("workflow roles must be a non-empty list")
    roles: list[WorkflowRole] = []
    for raw in role_values:
        role = _mapping(raw, "role")
        role_id, prompt, output = role.get("id"), role.get("prompt"), role.get("output")
        if any(type(item) is not str or not item.strip() for item in (role_id, prompt, output)):
            raise ValueError("workflow roles require id, prompt, and output")
        roles.append(WorkflowRole(role_id, prompt, _safe_relative(output), role.get("requiresEvidence") is True))
    role_ids = [role.id for role in roles]
    if len(set(role_ids)) != len(role_ids):
        raise ValueError("workflow role ids must be unique")

    artifact_values = document.get("artifacts")
    if type(artifact_values) is not list or not artifact_values:
        raise ValueError("workflow artifacts must be a non-empty list")
    artifacts = tuple(_safe_relative(item) for item in artifact_values)

    gates: list[WorkflowGate] = []
    for raw in document.get("gates", []):
        gate = _mapping(raw, "gate")
        gate_id, before_role = gate.get("id"), gate.get("beforeRole")
        if type(gate_id) is not str or not gate_id or before_role not in role_ids:
            raise ValueError("workflow gates require an id and existing beforeRole")
        gates.append(WorkflowGate(gate_id, before_role, gate.get("requiredByDefault") is True))
    return WorkflowPack(root, workflow_id, mode, tuple(roles), artifacts, tuple(gates))


def execute_workflow(
    pack: WorkflowPack,
    provider: AgentProvider,
    start_spec: ProviderStartSpec,
) -> WorkflowExecution:
    """Run roles in declaration order and stop after the first non-success state."""
    handle = provider.start(start_spec)
    completed: list[str] = []
    states: list[TaskState] = []
    try:
        for role in pack.roles:
            session = provider.create_session(
                handle,
                TaskSpec(f"{pack.id}:{role.id}", role.prompt),
            )
            events = tuple(provider.stream_events(handle, session))
            state = events[-1].state if events else TaskState.FAILED
            states.append(state)
            if state is not TaskState.SUCCEEDED:
                break
            completed.append(role.id)
    finally:
        provider.stop(handle)
    artifacts = pack.artifacts if len(completed) == len(pack.roles) else ()
    return WorkflowExecution(pack.id, tuple(completed), tuple(states), artifacts)
