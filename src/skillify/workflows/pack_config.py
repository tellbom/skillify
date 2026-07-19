"""Declarative Workflow Pack configuration; execution belongs to the selected provider."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from skillify.agent.permissions import PermissionManifest
from skillify.validator import validate_skill_dir


SUPPORTED_RUNTIMES = frozenset({"opencode", "claude-code"})
DELEGATION_MODES = frozenset({"adaptive", "suggested", "required"})
EXECUTION_MODES = frozenset({"single", "delegated", "team"})


@dataclass(frozen=True)
class WorkflowGate:
    id: str
    required_by_default: bool
    required_for_web: bool


@dataclass(frozen=True)
class DelegationConfig:
    mode: str = "suggested"
    user_approval: str = "required"
    executor_managed: bool = True


@dataclass(frozen=True)
class ExecutionConfig:
    mode: str = "single"
    collaboration_runtime: str | None = None
    preferred_cli: str = "opencode"


@dataclass(frozen=True)
class TeamPolicy:
    min_workers: int = 2
    max_active_workers: int = 3
    max_parallel_model_calls: int = 2
    max_team_duration_minutes: int = 120
    require_independent_review: bool = True


@dataclass(frozen=True)
class WorkflowPack:
    path: Path
    id: str
    runtimes: tuple[str, ...]
    entry_agent: str
    skills: tuple[str, ...]
    mcp: tuple[str, ...]
    mode: str
    artifacts: tuple[str, ...]
    gates: tuple[WorkflowGate, ...]
    permissions: PermissionManifest
    delegation: DelegationConfig
    execution: ExecutionConfig
    team_policy: TeamPolicy


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


def _string_list(value: object, field: str) -> tuple[str, ...]:
    values = [value] if type(value) is str else value
    if type(values) is not list or not values or any(type(item) is not str or not item.strip() for item in values):
        raise ValueError(f"workflow {field} must be a non-empty string list")
    if len(set(values)) != len(values):
        raise ValueError(f"workflow {field} must be unique")
    return tuple(values)


def load_workflow_pack(path: Path) -> WorkflowPack:
    root = Path(path)
    validation = validate_skill_dir(root)
    if not validation.ok:
        messages = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise ValueError(f"invalid Skillify pack: {messages}")
    manifest = _mapping(yaml.safe_load((root / "skill.yaml").read_text(encoding="utf-8")), "manifest")
    document = _mapping(yaml.safe_load((root / "workflow.yaml").read_text(encoding="utf-8")), "definition")
    if document.get("workflowVersion") != 1:
        raise ValueError("workflowVersion must be 1")
    workflow_id = document.get("id")
    mode = document.get("mode")
    entry_agent = document.get("entryAgent")
    if type(workflow_id) is not str or not workflow_id:
        raise ValueError("workflow id is required")
    if mode not in {"read-only", "workspace-write"}:
        raise ValueError("workflow mode is unsupported")
    if type(entry_agent) is not str or not entry_agent.strip():
        raise ValueError("workflow entryAgent is required")
    runtimes = _string_list(document.get("runtime"), "runtime")
    if not set(runtimes) <= SUPPORTED_RUNTIMES:
        raise ValueError("workflow runtime is unsupported")
    skills = _string_list(document.get("skills"), "skills")
    mcp_value = document.get("mcp", [])
    mcp = () if mcp_value == [] else _string_list(mcp_value, "mcp")
    artifacts = tuple(_safe_relative(item) for item in document.get("artifacts", []))
    if not artifacts:
        raise ValueError("workflow artifacts are required")
    gates = []
    for raw in document.get("gates", []):
        gate = _mapping(raw, "gate")
        gate_id = gate.get("id")
        if type(gate_id) is not str or not gate_id:
            raise ValueError("workflow gate id is required")
        gates.append(WorkflowGate(
            gate_id,
            gate.get("requiredByDefault") is True,
            gate.get("webRequired") is True,
        ))
    permission_value = manifest.get("permissions") or {}
    raw_delegation = document.get("delegation") or {}
    delegation = _mapping(raw_delegation, "delegation")
    delegation_config = DelegationConfig(
        mode=delegation.get("mode", "suggested"),
        user_approval=delegation.get("user_approval", "required"),
        executor_managed=delegation.get("executor_managed", True),
    )
    if (
        delegation_config.mode not in DELEGATION_MODES
        or delegation_config.user_approval not in {"required", "optional"}
        or delegation_config.executor_managed is not True
    ):
        raise ValueError("workflow delegation configuration is unsupported")
    raw_execution = _mapping(document.get("execution") or {}, "execution")
    execution = ExecutionConfig(
        mode=raw_execution.get("mode", "single"),
        collaboration_runtime=raw_execution.get("collaboration_runtime"),
        preferred_cli=raw_execution.get("preferred_cli", runtimes[0]),
    )
    if execution.mode not in EXECUTION_MODES or execution.preferred_cli not in SUPPORTED_RUNTIMES:
        raise ValueError("workflow execution configuration is unsupported")
    if execution.preferred_cli not in runtimes:
        raise ValueError("workflow preferred CLI must be a supported pack runtime")
    if execution.mode == "team":
        if execution.collaboration_runtime != "shogun":
            raise ValueError("team execution requires collaboration_runtime=shogun")
    elif execution.collaboration_runtime is not None:
        raise ValueError("collaboration runtime is only valid for team execution")
    raw_team_policy = _mapping(document.get("team_policy") or {}, "team_policy")
    team_policy = TeamPolicy(
        min_workers=raw_team_policy.get("min_workers", 2),
        max_active_workers=raw_team_policy.get("max_active_workers", 3),
        max_parallel_model_calls=raw_team_policy.get("max_parallel_model_calls", 2),
        max_team_duration_minutes=raw_team_policy.get("max_team_duration_minutes", 120),
        require_independent_review=raw_team_policy.get("require_independent_review", True),
    )
    numeric_policy = (
        team_policy.min_workers, team_policy.max_active_workers,
        team_policy.max_parallel_model_calls, team_policy.max_team_duration_minutes,
    )
    if (
        any(type(value) is not int or value < 1 for value in numeric_policy)
        or team_policy.min_workers > team_policy.max_active_workers
        or team_policy.max_parallel_model_calls > team_policy.max_active_workers
        or type(team_policy.require_independent_review) is not bool
    ):
        raise ValueError("workflow team policy is unsupported")
    return WorkflowPack(
        root, workflow_id, runtimes, entry_agent, skills, mcp, mode, artifacts, tuple(gates),
        PermissionManifest.from_value(f"workflow:{workflow_id}", permission_value), delegation_config,
        execution, team_policy,
    )


def approval_required(
    pack: WorkflowPack,
    gate_id: str,
    *,
    origin: str,
    override: bool | None = None,
) -> bool:
    if origin not in {"local", "web"}:
        raise ValueError("workflow origin must be local or web")
    if override is not None and type(override) is not bool:
        raise ValueError("approval override must be a boolean")
    gate = next((item for item in pack.gates if item.id == gate_id), None)
    if gate is None:
        raise ValueError(f"unknown workflow gate: {gate_id}")
    if override is not None:
        return override
    return gate.required_for_web if origin == "web" else gate.required_by_default
