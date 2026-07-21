"""Workflow Pack projection commands backed by the transactional capability engine."""

from __future__ import annotations

import hmac
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import typer
import yaml
from rich.console import Console

from skillify.agent.capability_lock import CapabilityKind, CapabilityLockStore
from skillify.agent.opencode_config import (
    CapabilitySource, OpenCodeConfigError, OpenCodeScopePaths,
    apply_install, apply_uninstall, plan_install, plan_uninstall, rollback_install,
)
from skillify.agent.permissions import merge_permissions
from skillify.common.config import load_agent_paths
from skillify.install.resolver import Coordinate
from skillify.mcp.registry import McpRegistry
from skillify.packaging.pack import pack_skill
from skillify.workflows import load_workflow_pack


pack_app = typer.Typer(help="Install, update, roll back, or remove a Workflow Pack projection.")


def _paths(project: Path) -> tuple[OpenCodeScopePaths, CapabilityLockStore]:
    root = project.resolve(strict=True)
    agent_paths = load_agent_paths()
    return (
        OpenCodeScopePaths.project(root, cache_root=agent_paths.cache_dir / "capabilities"),
        CapabilityLockStore(agent_paths.state_dir / "capability-locks"),
    )


def _source(pack_dir: Path, commit: str, checksum: str) -> CapabilitySource:
    pack = load_workflow_pack(pack_dir.resolve(strict=True))
    manifest = yaml.safe_load((pack.path / "skill.yaml").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="skillify-pack-verify-") as temporary:
        actual_checksum = pack_skill(pack.path, Path(temporary)).sha256
    if not hmac.compare_digest(actual_checksum, checksum):
        raise ValueError("Workflow Pack checksum does not match its deterministic artifact")
    coordinate = Coordinate(
        CapabilityKind.WORKFLOW,
        f"{manifest['namespace']}/{manifest['name']}",
        str(manifest["version"]),
    )
    return CapabilitySource(
        root=pack.path, coordinate=coordinate,
        forgejo_release=f"v{coordinate.version}", commit=commit, checksum=checksum,
        dependencies=(), permissions=merge_permissions((pack.permissions,)),
    )


def _install(
    pack_dir: Path, project: Path, commit: str, checksum: str,
    dry_run: bool, console: Console,
) -> None:
    source = _source(pack_dir, commit, checksum)
    paths, store = _paths(project)
    plan = plan_install(
        source, paths=paths, lock_store=store, mcp_registry=McpRegistry(),
        installed_at=datetime.now(timezone.utc).isoformat(),
    )
    result = apply_install(plan, dry_run=dry_run)
    verb = "Planned" if dry_run else ("Updated" if result.changed else "Installed")
    console.print(
        f"[green]{verb}[/green] {source.coordinate} lock={result.lock.digest} "
        f"changes={sum(item.kind.value != 'unchanged' for item in result.mutations)}"
    )


@pack_app.command("install")
def install_pack(
    pack_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    project: Path = typer.Option(Path.cwd(), "--project", exists=True, file_okay=False),
    commit: str = typer.Option(..., "--commit", help="Published Forgejo commit SHA."),
    checksum: str = typer.Option(..., "--checksum", help="Verified release artifact SHA256."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        _install(pack_dir, project, commit, checksum, dry_run, Console())
    except (ValueError, OSError, OpenCodeConfigError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@pack_app.command("update")
def update_pack(
    pack_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    project: Path = typer.Option(Path.cwd(), "--project", exists=True, file_okay=False),
    commit: str = typer.Option(..., "--commit"),
    checksum: str = typer.Option(..., "--checksum"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        _install(pack_dir, project, commit, checksum, dry_run, Console())
    except (ValueError, OSError, OpenCodeConfigError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@pack_app.command("rollback")
def rollback_pack(
    digest: str = typer.Argument(..., help="Historical lock digest printed by install/update."),
    project: Path = typer.Option(Path.cwd(), "--project", exists=True, file_okay=False),
) -> None:
    try:
        paths, store = _paths(project)
        result = rollback_install(digest, paths=paths, lock_store=store)
        Console().print(f"[green]Rolled back[/green] lock={result.lock.digest}")
    except (ValueError, OSError, OpenCodeConfigError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@pack_app.command("remove")
def remove_pack(
    identifier: str = typer.Argument(..., help="Installed namespace/name."),
    project: Path = typer.Option(Path.cwd(), "--project", exists=True, file_okay=False),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        namespace, name = identifier.split("/", 1)
        paths, store = _paths(project)
        lock = store.read_current(CapabilityKind.WORKFLOW, namespace, name)
        if lock is None:
            raise ValueError("Workflow Pack is not installed in the selected scope")
        result = apply_uninstall(
            plan_uninstall(lock, paths=paths, lock_store=store), dry_run=dry_run,
        )
        Console().print(
            f"[green]{'Planned removal' if dry_run else 'Removed'}[/green] "
            f"workflow:{identifier}@{result.lock.version}"
        )
    except (ValueError, OSError, OpenCodeConfigError) as exc:
        raise typer.BadParameter(str(exc)) from exc
