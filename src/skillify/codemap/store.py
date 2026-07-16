"""Incremental local JSON store for Code Map graphs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from skillify.codemap.schema import (
    CodeEdge,
    CodeGraph,
    CodeNode,
    EdgeKind,
    Evidence,
    NodeKind,
    stable_id,
)


@dataclass(frozen=True)
class StoreUpdate:
    graph: CodeGraph
    reused_nodes: int
    removed_nodes: int
    error: str | None = None


def graph_from_index(index: Mapping[str, Any]) -> CodeGraph:
    if index.get("schemaVersion") != 1 or type(index.get("files")) is not list:
        raise ValueError("pipeline index must use schemaVersion 1 with files")
    repository_id = stable_id("repository", ".")
    nodes = [CodeNode(repository_id, NodeKind.REPOSITORY, ".")]
    edges: list[CodeEdge] = []
    for file_value in index["files"]:
        if type(file_value) is not dict:
            raise ValueError("pipeline file entry must be an object")
        path = str(file_value["path"])
        file_id = stable_id("file", path)
        file_evidence = Evidence(path, 1, 1)
        nodes.append(CodeNode(
            file_id, NodeKind.FILE, path, file_evidence,
            {
                "language": file_value.get("language"),
                "contentHash": file_value.get("contentHash"),
                "summary": file_value.get("summary", ""),
                "parseError": file_value.get("parseError"),
            },
        ))
        edges.append(CodeEdge(
            stable_id("edge", EdgeKind.CONTAINS.value, repository_id, file_id),
            EdgeKind.CONTAINS, repository_id, file_id, 1.0, "pipeline", file_evidence,
        ))
        for symbol in file_value.get("symbols", []):
            name = str(symbol["name"])
            kind = str(symbol["kind"])
            line = int(symbol["line"])
            end_line = int(symbol.get("endLine", line))
            symbol_id = stable_id("symbol", path, kind, name)
            evidence = Evidence(path, line, end_line)
            nodes.append(CodeNode(
                symbol_id, NodeKind.SYMBOL, name, evidence,
                {"symbolKind": kind, "parser": symbol.get("parser")},
            ))
            edges.append(CodeEdge(
                stable_id("edge", EdgeKind.CONTAINS.value, file_id, symbol_id),
                EdgeKind.CONTAINS, file_id, symbol_id, 1.0, "pipeline", evidence,
            ))
    return CodeGraph(
        repository_hash=str(index.get("repositoryHash", "")),
        nodes=tuple(sorted(nodes, key=lambda node: node.id)),
        edges=tuple(sorted(edges, key=lambda edge: edge.id)),
    )


class CodeMapStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def read(self) -> CodeGraph:
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if type(value) is not dict:
            raise ValueError("stored Code Map must be an object")
        return CodeGraph.from_dict(value)

    def _read_optional(self) -> CodeGraph | None:
        try:
            return self.read()
        except FileNotFoundError:
            return None

    def update(self, index: Mapping[str, Any]) -> StoreUpdate:
        previous = self._read_optional()
        graph = graph_from_index(index)
        old_ids = set() if previous is None else {node.id for node in previous.nodes}
        new_ids = {node.id for node in graph.nodes}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(graph.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return StoreUpdate(
            graph=graph,
            reused_nodes=len(old_ids & new_ids),
            removed_nodes=len(old_ids - new_ids),
        )

    def try_update(self, index: Mapping[str, Any]) -> StoreUpdate:
        previous = self._read_optional()
        try:
            return self.update(index)
        except (KeyError, TypeError, ValueError) as exc:
            if previous is None:
                raise
            return StoreUpdate(previous, len(previous.nodes), 0, str(exc))
