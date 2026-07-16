"""Read-only evidence queries over a stored Code Map graph."""

from __future__ import annotations

from typing import Any

from skillify.codemap.schema import CodeGraph, EdgeKind, NodeKind


QUERY_TYPES = ("modules", "entrypoints", "dependencies", "apis", "data", "tests")

_NODE_QUERIES = {
    "modules": {NodeKind.MODULE, NodeKind.FILE},
    "entrypoints": {NodeKind.ENTRYPOINT, NodeKind.SYMBOL},
    "apis": {NodeKind.API_ENDPOINT},
    "data": {NodeKind.DATA_ENTITY},
    "tests": {NodeKind.TEST},
}


def _matches(value: str, term: str) -> bool:
    return not term or term.casefold() in value.casefold()


def _node_result(node: object) -> dict[str, Any]:
    evidence = getattr(node, "evidence")
    return {
        "id": getattr(node, "id"),
        "kind": getattr(node, "kind").value,
        "name": getattr(node, "name"),
        "evidence": None if evidence is None else evidence.as_dict(),
    }


def query_graph(
    graph: CodeGraph,
    query_type: str,
    *,
    term: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return bounded metadata and evidence positions; never return source text."""
    if query_type not in QUERY_TYPES:
        raise ValueError(f"query_type must be one of: {', '.join(QUERY_TYPES)}")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    nodes = {node.id: node for node in graph.nodes}
    if query_type != "dependencies":
        kinds = _NODE_QUERIES[query_type]
        return [
            _node_result(node)
            for node in sorted(graph.nodes, key=lambda item: (item.kind.value, item.name, item.id))
            if node.kind in kinds and _matches(node.name, term)
        ][:limit]

    results: list[dict[str, Any]] = []
    for edge in sorted(graph.edges, key=lambda item: item.id):
        if edge.kind not in {EdgeKind.IMPORTS, EdgeKind.CALLS}:
            continue
        source = nodes.get(edge.source)
        target = nodes.get(edge.target)
        label = " -> ".join(
            part.name if part is not None else identifier
            for part, identifier in ((source, edge.source), (target, edge.target))
        )
        if not _matches(label, term):
            continue
        evidence = edge.evidence or (source.evidence if source is not None else None)
        results.append({
            "id": edge.id,
            "kind": edge.kind.value,
            "name": label,
            "source": edge.source,
            "target": edge.target,
            "confidence": edge.confidence,
            "sourceLabel": edge.source_label,
            "evidence": None if evidence is None else evidence.as_dict(),
        })
        if len(results) == limit:
            break
    return results
