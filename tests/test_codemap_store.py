from __future__ import annotations

from pathlib import Path

import pytest

from skillify.codemap.pipeline import build_code_map
from skillify.codemap.schema import (
    CodeEdge,
    EdgeKind,
    NodeKind,
    stable_id,
)
from skillify.codemap.store import CodeMapStore


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_stable_ids_survive_content_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    store = CodeMapStore(tmp_path / "graph.json")
    _write(repo, "app.py", "def run():\n    return 1\n")
    first = store.update(build_code_map(repo)).graph

    _write(repo, "app.py", "def run():\n    return 2\n")
    second = store.update(build_code_map(repo)).graph

    first_ids = {(node.kind, node.name): node.id for node in first.nodes}
    second_ids = {(node.kind, node.name): node.id for node in second.nodes}
    assert first_ids[(NodeKind.FILE, "app.py")] == second_ids[(NodeKind.FILE, "app.py")]
    assert first_ids[(NodeKind.SYMBOL, "run")] == second_ids[(NodeKind.SYMBOL, "run")]


def test_incremental_store_reports_reused_and_removed_nodes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    store = CodeMapStore(tmp_path / "graph.json")
    _write(repo, "keep.py", "def keep():\n    pass\n")
    _write(repo, "remove.py", "def remove():\n    pass\n")
    first = store.update(build_code_map(repo))
    assert first.reused_nodes == 0

    (repo / "remove.py").unlink()
    second = store.update(build_code_map(repo))

    assert second.reused_nodes >= 3  # repository, keep.py, keep symbol
    assert second.removed_nodes == 2
    loaded = store.read()
    assert loaded == second.graph
    assert all(node.name != "remove.py" for node in loaded.nodes)


def test_edges_include_confidence_source_and_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo, "main.go", "package main\nfunc main() {}\n")
    graph = CodeMapStore(tmp_path / "graph.json").update(build_code_map(repo)).graph

    assert {node.kind for node in graph.nodes} >= {
        NodeKind.REPOSITORY, NodeKind.FILE, NodeKind.SYMBOL,
    }
    assert graph.edges
    assert all(edge.confidence == 1.0 for edge in graph.edges)
    assert all(edge.source_label == "pipeline" for edge in graph.edges)
    assert any(edge.evidence and edge.evidence.path == "main.go" for edge in graph.edges)


def test_schema_supports_all_planned_node_and_edge_kinds() -> None:
    assert {item.value for item in NodeKind} == {
        "repository", "module", "file", "symbol", "api_endpoint",
        "data_entity", "test", "entrypoint",
    }
    assert {item.value for item in EdgeKind} == {
        "contains", "imports", "calls", "implements", "reads_writes",
        "tests", "routes_to",
    }
    with pytest.raises(ValueError, match="confidence"):
        CodeEdge(
            id=stable_id("edge", "bad"), kind=EdgeKind.CALLS,
            source="a", target="b", confidence=1.5,
            source_label="inference", evidence=None,
        )


def test_generation_failure_can_be_reported_without_replacing_last_good_graph(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    store = CodeMapStore(tmp_path / "graph.json")
    _write(repo, "ok.py", "def ok():\n    pass\n")
    good = store.update(build_code_map(repo)).graph

    result = store.try_update({"schemaVersion": 999})

    assert result.graph == good
    assert result.error
    assert store.read() == good
