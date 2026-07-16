from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from skillify.cli.main import app
from skillify.codemap.mcp_server import CodeMapMcpServer
from skillify.codemap.query import QUERY_TYPES, query_graph
from skillify.codemap.schema import (
    CodeEdge,
    CodeGraph,
    CodeNode,
    EdgeKind,
    Evidence,
    NodeKind,
    stable_id,
)


runner = CliRunner()


def _graph() -> CodeGraph:
    specs = (
        ("module", NodeKind.MODULE, "billing", "src/billing.py", 1),
        ("entry", NodeKind.ENTRYPOINT, "main", "src/main.py", 8),
        ("api", NodeKind.API_ENDPOINT, "POST /invoices", "src/api.py", 12),
        ("data", NodeKind.DATA_ENTITY, "Invoice", "src/models.py", 4),
        ("test", NodeKind.TEST, "test_create_invoice", "tests/test_api.py", 9),
    )
    nodes = tuple(
        CodeNode(stable_id(key), kind, name, Evidence(path, line, line))
        for key, kind, name, path, line in specs
    )
    dependency = CodeEdge(
        stable_id("dependency"), EdgeKind.IMPORTS, nodes[1].id, nodes[0].id,
        0.95, "fixture-parser", Evidence("src/main.py", 2, 2),
    )
    return CodeGraph("fixture-hash", nodes, (dependency,))


def _write_graph(path: Path) -> None:
    path.write_text(json.dumps(_graph().as_dict()), encoding="utf-8")


def test_six_supported_query_types_return_evidence_positions() -> None:
    graph = _graph()

    for query_type in QUERY_TYPES:
        results = query_graph(graph, query_type)
        assert results, query_type
        assert results[0]["evidence"]["path"]
        assert results[0]["evidence"]["line"] >= 1


def test_mcp_returns_positions_but_never_repository_source(tmp_path: Path) -> None:
    path = tmp_path / "code-map.json"
    _write_graph(path)

    result = CodeMapMcpServer(path).handle("tools/call", {
        "name": "query_code_map",
        "arguments": {"queryType": "apis"},
    })

    payload = result["structuredContent"]
    assert payload["results"][0]["evidence"] == {
        "path": "src/api.py", "line": 12, "endLine": 12,
    }
    assert "source" not in payload["results"][0]
    assert "POST /invoices" in result["content"][0]["text"]


def test_cli_build_status_query_and_export(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    graph_path = tmp_path / "code-map.json"

    built = runner.invoke(app, [
        "map", "build", str(repository), "--output", str(graph_path),
    ])
    assert built.exit_code == 0
    assert json.loads(built.stdout)["nodes"] == 3

    status = runner.invoke(app, ["map", "status", "--path", str(graph_path)])
    assert status.exit_code == 0
    assert json.loads(status.stdout)["schemaVersion"] == 1

    queried = runner.invoke(app, [
        "map", "query", "entrypoints", "main", "--path", str(graph_path),
    ])
    assert queried.exit_code == 0
    assert json.loads(queried.stdout)["results"][0]["evidence"]["path"] == "app.py"

    exported = tmp_path / "export" / "graph.json"
    result = runner.invoke(app, [
        "map", "export", str(exported), "--path", str(graph_path),
    ])
    assert result.exit_code == 0
    assert json.loads(exported.read_text(encoding="utf-8"))["schemaVersion"] == 1
