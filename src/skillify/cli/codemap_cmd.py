"""CLI commands for the endpoint-local human Code Map visualizer."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import typer

from skillify.codemap.snapshot import SnapshotError, build_snapshot
from skillify.codemap.visualizer import GitNexusVisualizer, load_manifest, resolve_workspace_alias
from skillify.common.config import load_agent_local_config, load_agent_paths


codemap_app = typer.Typer(help="Manage the human-facing endpoint Code Map.", no_args_is_help=True)
visualize_app = typer.Typer(help="Manage the pinned GitNexus visualizer.", no_args_is_help=True)
codemap_app.add_typer(visualize_app, name="visualize")


def _visualizer() -> GitNexusVisualizer:
    paths = load_agent_paths()
    default_manifest = Path(__file__).resolve().parents[3] / "infra" / "offline" / "gitnexus-visualizer-manifest.json"
    manifest_path = Path(os.environ.get("SKILLIFY_GITNEXUS_MANIFEST", default_manifest))
    runtime_raw = os.environ.get("SKILLIFY_GITNEXUS_ROOT")
    if not runtime_raw:
        raise typer.BadParameter("SKILLIFY_GITNEXUS_ROOT is required")
    return GitNexusVisualizer(
        manifest=load_manifest(manifest_path), runtime_root=Path(runtime_raw),
        state_root=paths.state_dir / "codemap-visualizer",
    )


def _workspace(alias: str) -> Path:
    paths = load_agent_paths()
    config = load_agent_local_config(paths)
    aliases = dict(config.workspace_aliases)
    for raw in config.allowed_workspaces:
        aliases.setdefault(Path(raw).name, raw)
    return resolve_workspace_alias(alias, aliases)


@visualize_app.command("start")
def start(
    workspace: str = typer.Option(..., "--workspace", help="Configured workspace alias."),
    port: int = typer.Option(4747, "--port"),
) -> None:
    """Create a local snapshot, index it, and start GitNexus on localhost."""
    typer.echo(json.dumps(asdict(_visualizer().start(workspace, _workspace(workspace), port=port)), sort_keys=True))


@visualize_app.command("status")
def status(workspace: str = typer.Option(..., "--workspace")) -> None:
    """Show local visualizer state without exposing source or index data."""
    typer.echo(json.dumps(asdict(_visualizer().status(workspace)), sort_keys=True))


@visualize_app.command("open")
def open_visualizer(workspace: str = typer.Option(..., "--workspace")) -> None:
    """Open the running visualizer in Chrome on this endpoint."""
    typer.echo(json.dumps(asdict(_visualizer().open(workspace)), sort_keys=True))


@visualize_app.command("stop")
def stop(workspace: str = typer.Option(..., "--workspace")) -> None:
    """Stop the visualizer for a workspace."""
    typer.echo(json.dumps(asdict(_visualizer().stop(workspace)), sort_keys=True))


@visualize_app.command("doctor")
def doctor() -> None:
    """Check the pinned runtime, noncommercial policy, and local Chrome."""
    typer.echo(json.dumps(_visualizer().doctor(), sort_keys=True))


@codemap_app.command("snapshot")
def snapshot(
    workspace: str = typer.Option(..., "--workspace", help="Configured workspace alias."),
    output: Path = typer.Option(..., "--output", help="Destination directory for the snapshot tar+SHA256."),
) -> None:
    """Package the committed HEAD of a workspace (git-tracked files only) into a reproducible tar+SHA256."""
    try:
        result = build_snapshot(_workspace(workspace), output)
    except SnapshotError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(asdict(result), sort_keys=True, default=str))
