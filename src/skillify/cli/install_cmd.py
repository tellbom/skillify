"""`skillctl install` / `update` / `remove` — CLI wiring for T1.4/T1.4a/T1.5."""

from __future__ import annotations

import shutil

import typer
from rich.console import Console

from skillify.common.config import load_config
from skillify.common.identifier import InvalidIdentifier, parse_identifier
from skillify.install.dependencies import DependencyError, install_with_dependencies
from skillify.install.installer import InstallError
from skillify.install.lock import read_lock, remove_lock


def run_install(
    *, identifier: str, targets: list[str], source_override: str | None, console: Console, err_console: Console
) -> None:
    cfg = load_config()
    try:
        installed = install_with_dependencies(identifier, cfg=cfg, source_override=source_override)
    except (InstallError, DependencyError, InvalidIdentifier) as exc:
        err_console.print(f"[red]install failed:[/red] {exc}")
        raise typer.Exit(code=1)

    root_key = identifier.split("@", 1)[0]
    lock = installed[root_key] if root_key in installed else next(iter(installed.values()))

    for dep_key, dep_lock in installed.items():
        if dep_key == lock.identifier:
            continue
        console.print(f"[green]Installed dependency[/green] {dep_lock.identifier}@{dep_lock.version}")

    console.print(f"[green]Installed[/green] {lock.identifier}@{lock.version} -> {cfg.skills_dir / lock.namespace / lock.name}")
    if lock.venvPath:
        console.print(f"  venv: {lock.venvPath} ({len(lock.pythonDeps)} python dep(s))")

    if cfg.reporting_enabled and cfg.web_base_url:
        from skillify.common.telemetry import report_skill_event

        report_skill_event(cfg, namespace=lock.namespace, name=lock.name, version=lock.version, event_type="install")

    if not targets:
        from skillify.install.agent_defaults import auto_select_targets

        targets = auto_select_targets(lock.declaredTargets)
        if targets:
            console.print(f"  (no --target given, auto-selected: {', '.join(targets)})")

    if targets:
        from skillify.install.projector import project_to_targets

        try:
            project_to_targets(cfg, lock, targets)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user either way
            err_console.print(f"[red]install succeeded but agent projection failed:[/red] {exc}")
            raise typer.Exit(code=1)
        console.print(f"  projected to: {', '.join(targets)}")


def run_update(*, identifier: str, console: Console, err_console: Console) -> None:
    cfg = load_config()
    try:
        namespace, name, _ = parse_identifier(identifier)
    except InvalidIdentifier as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    existing = read_lock(cfg.locks_dir, namespace, name)
    if existing is None:
        err_console.print(f"[red]{namespace}/{name} is not installed — use `skillctl install` first[/red]")
        raise typer.Exit(code=1)

    try:
        installed = install_with_dependencies(f"{namespace}/{name}", cfg=cfg)
    except (InstallError, DependencyError) as exc:
        err_console.print(f"[red]update failed:[/red] {exc}")
        raise typer.Exit(code=1)
    lock = installed[f"{namespace}/{name}"]

    for dep_key, dep_lock in installed.items():
        if dep_key == lock.identifier:
            continue
        console.print(f"[green]Installed dependency[/green] {dep_lock.identifier}@{dep_lock.version}")

    if lock.version == existing.version:
        console.print(f"[green]{lock.identifier}@{lock.version} is already the latest[/green]")
    else:
        console.print(f"[green]Updated[/green] {lock.identifier}: {existing.version} -> {lock.version}")

    if existing.targets:
        from skillify.install.projector import project_to_targets

        project_to_targets(cfg, lock, existing.targets)


def run_remove(*, identifier: str, console: Console, err_console: Console) -> None:
    cfg = load_config()
    try:
        namespace, name, _ = parse_identifier(identifier)
    except InvalidIdentifier as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    lock = read_lock(cfg.locks_dir, namespace, name)
    if lock is None:
        err_console.print(f"[red]{namespace}/{name} is not installed[/red]")
        raise typer.Exit(code=1)

    if lock.targets:
        from skillify.install.projector import remove_projections

        remove_projections(cfg, lock, lock.targets)

    skill_dir = cfg.skills_dir / namespace / name
    shutil.rmtree(skill_dir, ignore_errors=True)
    if lock.venvPath:
        shutil.rmtree(lock.venvPath, ignore_errors=True)
    remove_lock(cfg.locks_dir, namespace, name)

    console.print(f"[green]Removed[/green] {namespace}/{name}")
