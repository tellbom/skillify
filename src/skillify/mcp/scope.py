"""Shared least-privilege authorization for development connectors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ToolAccess(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ToolScope:
    name: str
    access: ToolAccess
    required_scopes: frozenset[str]


@dataclass(frozen=True)
class ConnectorPolicy:
    token_scopes: frozenset[str]
    allowed_write_tools: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if any(scope.casefold() in {"admin", "all", "repo:admin"} for scope in self.token_scopes):
            raise ValueError("administrator scopes must not be distributed to MCP connectors")

    def authorize(self, tool: ToolScope) -> None:
        if not tool.required_scopes <= self.token_scopes:
            raise PermissionError("connector token lacks the tool's minimum scope")
        if tool.access is ToolAccess.WRITE and tool.name not in self.allowed_write_tools:
            raise PermissionError("connector write tool requires explicit authorization")
