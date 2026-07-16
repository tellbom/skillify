"""Versioned Code Map graph schema with stable evidence-linked identities."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class NodeKind(str, Enum):
    REPOSITORY = "repository"
    MODULE = "module"
    FILE = "file"
    SYMBOL = "symbol"
    API_ENDPOINT = "api_endpoint"
    DATA_ENTITY = "data_entity"
    TEST = "test"
    ENTRYPOINT = "entrypoint"


class EdgeKind(str, Enum):
    CONTAINS = "contains"
    IMPORTS = "imports"
    CALLS = "calls"
    IMPLEMENTS = "implements"
    READS_WRITES = "reads_writes"
    TESTS = "tests"
    ROUTES_TO = "routes_to"


def stable_id(*parts: object) -> str:
    if not parts or any(type(part) is not str or not part for part in parts):
        raise ValueError("stable_id parts must be non-empty strings")
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"cm_{digest[:24]}"


@dataclass(frozen=True)
class Evidence:
    path: str
    line: int
    end_line: int

    def __post_init__(self) -> None:
        if not self.path or self.line < 1 or self.end_line < self.line:
            raise ValueError("evidence must contain a path and valid line range")

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "line": self.line, "endLine": self.end_line}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Evidence":
        return cls(str(value["path"]), int(value["line"]), int(value["endLine"]))


@dataclass(frozen=True)
class CodeNode:
    id: str
    kind: NodeKind
    name: str
    evidence: Evidence | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "name": self.name,
            "evidence": None if self.evidence is None else self.evidence.as_dict(),
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CodeNode":
        evidence = value.get("evidence")
        return cls(
            id=str(value["id"]), kind=NodeKind(value["kind"]), name=str(value["name"]),
            evidence=None if evidence is None else Evidence.from_dict(evidence),
            attributes=dict(value.get("attributes", {})),
        )


@dataclass(frozen=True)
class CodeEdge:
    id: str
    kind: EdgeKind
    source: str
    target: str
    confidence: float
    source_label: str
    evidence: Evidence | None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.source or not self.target or not self.source_label:
            raise ValueError("edge source, target, and source_label are required")

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "source": self.source,
            "target": self.target,
            "confidence": self.confidence,
            "sourceLabel": self.source_label,
            "evidence": None if self.evidence is None else self.evidence.as_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CodeEdge":
        evidence = value.get("evidence")
        return cls(
            id=str(value["id"]), kind=EdgeKind(value["kind"]),
            source=str(value["source"]), target=str(value["target"]),
            confidence=float(value["confidence"]),
            source_label=str(value["sourceLabel"]),
            evidence=None if evidence is None else Evidence.from_dict(evidence),
        )


@dataclass(frozen=True)
class CodeGraph:
    repository_hash: str
    nodes: tuple[CodeNode, ...]
    edges: tuple[CodeEdge, ...]
    schema_version: int = 1

    def as_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "repositoryHash": self.repository_hash,
            "nodes": [node.as_dict() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CodeGraph":
        if value.get("schemaVersion") != 1:
            raise ValueError("unsupported Code Map schema version")
        return cls(
            repository_hash=str(value["repositoryHash"]),
            nodes=tuple(CodeNode.from_dict(item) for item in value.get("nodes", [])),
            edges=tuple(CodeEdge.from_dict(item) for item in value.get("edges", [])),
        )
