"""Code Map build, status, query, and export commands."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import typer

from skillify.codemap.pipeline import build_code_map
from skillify.codemap.query import QUERY_TYPES, query_graph
from skillify.codemap.store import CodeMapStore


DEFAULT_MAP_PATH = Path(".skillify/code-map.json")
map_app = typer.Typer(help="Build and inspect a local evidence-linked Code Map.", no_args_is_help=True)


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, sort_keys=True))


@map_app.command("build")
def build(
    repository: Path = typer.Argument(Path("."), help="Repository to index."),
    output: Path = typer.Option(DEFAULT_MAP_PATH, "--output", "-o", help="Graph output path."),
    max_files: int = typer.Option(10_000, min=1, help="Maximum source files to index."),
) -> None:
    """Build a versioned Code Map for a local repository."""
    result = CodeMapStore(output).update(build_code_map(repository, max_files=max_files))
    _emit({
        "path": str(output),
        "repositoryHash": result.graph.repository_hash,
        "nodes": len(result.graph.nodes),
        "edges": len(result.graph.edges),
        "reusedNodes": result.reused_nodes,
        "removedNodes": result.removed_nodes,
    })


@map_app.command("status")
def status(
    path: Path = typer.Option(DEFAULT_MAP_PATH, "--path", "-p", help="Code Map path."),
) -> None:
    """Show concise metadata for an existing Code Map."""
    graph = CodeMapStore(path).read()
    _emit({
        "path": str(path),
        "schemaVersion": graph.schema_version,
        "repositoryHash": graph.repository_hash,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
    })


@map_app.command("query")
def query(
    query_type: str = typer.Argument(..., help=f"Query type: {', '.join(QUERY_TYPES)}."),
    term: str = typer.Argument("", help="Optional case-insensitive name filter."),
    path: Path = typer.Option(DEFAULT_MAP_PATH, "--path", "-p", help="Code Map path."),
    limit: int = typer.Option(50, min=1, max=500),
) -> None:
    """Query graph metadata and source positions without returning source text."""
    results = query_graph(CodeMapStore(path).read(), query_type, term=term, limit=limit)
    _emit({"queryType": query_type, "term": term, "results": results})


@map_app.command("export")
def export(
    destination: Path = typer.Argument(..., help="Destination JSON path."),
    path: Path = typer.Option(DEFAULT_MAP_PATH, "--path", "-p", help="Code Map path."),
) -> None:
    """Export the canonical graph JSON for read-only consumers."""
    CodeMapStore(path).read()  # Validate before copying.
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, destination)
    _emit({"source": str(path), "destination": str(destination)})
