"""Select the smallest declared MCP subset for one endpoint task."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from skillify.agent.permissions import PermissionManifest


@dataclass(frozen=True)
class McpPackageConfig:
    name: str
    command: str
    args: tuple[str, ...]
    environment: Mapping[str, str]
    tools: tuple[str, ...]
    context_budget: int
    permissions: PermissionManifest | None = None


@dataclass(frozen=True)
class McpInjectionPlan:
    servers: dict[str, dict[str, object]]
    allowed_tools: tuple[str, ...]
    downgraded: bool
    log: str | None


def select_task_mcp(
    requested: tuple[str, ...],
    catalog: Mapping[str, McpPackageConfig],
    *,
    runtime: str,
    workspace: Path,
    per_task_supported: bool = True,
) -> McpInjectionPlan:
    unknown = set(requested) - set(catalog)
    if unknown:
        raise ValueError(f"task requests unknown MCP packages: {sorted(unknown)}")
    selected: dict[str, dict[str, object]] = {}
    allowed_tools: list[str] = []
    for name in requested:
        package = catalog[name]
        if not package.tools or package.context_budget < 1:
            raise ValueError("MCP package requires tool summary and context budget")
        environment = {
            key: value.replace("{workspace}", str(workspace))
            for key, value in package.environment.items()
        }
        if runtime == "opencode":
            selected[name] = {
                "type": "local", "command": [package.command, *package.args],
                "environment": environment, "enabled": True,
            }
        elif runtime == "claude-code":
            selected[name] = {
                "type": "stdio", "command": package.command,
                "args": list(package.args), "env": environment,
            }
            allowed_tools.extend(
                f"mcp__{name}__{tool.replace('.', '_')}" for tool in package.tools
            )
        else:
            raise ValueError("unsupported MCP injection runtime")
    if per_task_supported:
        return McpInjectionPlan(selected, tuple(allowed_tools), False, None)
    return McpInjectionPlan(
        selected, tuple(allowed_tools), True,
        "executor lacks per-task MCP configuration; global installation remains permission-allowlisted",
    )
