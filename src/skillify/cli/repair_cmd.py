"""Operational repair commands for the derived index and namespace ownership."""

from __future__ import annotations

from rich.console import Console

from skillify.common.config import load_config
from skillify.common.identifier import InvalidIdentifier, parse_identifier
from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.ownership import release_namespace
from skillify.index.rebuild import IndexRebuildError, rebuild_all, rebuild_repository
from skillify.publish.forgejo_client import ForgejoError


def run_rebuild_index(*, identifier: str | None, all_repositories: bool, console: Console) -> bool:
    cfg = load_config()
    if all_repositories == (identifier is not None):
        console.print("[red]Choose exactly one of <namespace/name> or --all.[/red]")
        return False
    try:
        if all_repositories:
            result = rebuild_all(cfg)
        else:
            namespace, name, version = parse_identifier(identifier or "")
            if version is not None:
                console.print("[red]Rebuild accepts namespace/name without a version.[/red]")
                return False
            result = rebuild_repository(cfg, cfg.forgejo_org or namespace, name)
    except (IndexRebuildError, InvalidIdentifier, ForgejoError) as exc:
        console.print(f"[red]Index rebuild failed:[/red] {exc}")
        return False
    console.print(
        f"[green]Index rebuild complete[/green]: repositories={result.repositories}, "
        f"indexed={result.indexed}, skipped={result.skipped}, failed={result.failed}"
    )
    return result.failed == 0


def run_release_namespace(
    *, namespace: str, expected_owner: str, confirmed: bool, console: Console
) -> bool:
    if not confirmed:
        console.print("[red]Refusing to release ownership without --yes.[/red]")
        return False
    cfg = load_config()
    if not cfg.index_db_url:
        console.print("[red]index_db_url not configured.[/red]")
        return False
    engine = make_engine(cfg.index_db_url)
    init_db(engine)
    with session_scope(engine) as session:
        deleted = release_namespace(session, namespace=namespace, expected_owner=expected_owner)
    if not deleted:
        console.print("[yellow]No matching namespace ownership row was changed.[/yellow]")
        return False
    console.print(f"[green]Released namespace[/green] {namespace} from {expected_owner}.")
    return True
