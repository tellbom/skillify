"""skillctl — Skillify CLI (Typer app). See TASKS.md M1 for the command roadmap.

Command implementation status (tracked against TASKS.md task IDs):
  validate   T0.2  implemented
  init       T1.1a implemented
  doctor     T1.1b implemented
  publish    T1.3  implemented (Forgejo Release upload)
  install    T1.4/T1.4a/T1.5 implemented (download, verify, venv, deps, projection)
  list       T1.4  implemented (reads local locks)
  update     T1.4  implemented (reinstall latest matching lock's target)
  remove     T1.4a implemented (removes neutral dir + agent projections)
  search     M3    not implemented — needs the web/index backend (T3.1), out of CLI-only MVP scope
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from skillify import __version__

app = typer.Typer(
    name="skillctl",
    help="Skillify CLI — install/publish/manage skills against a private Skillify deployment.",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"skillctl {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """Skillify CLI."""


def _not_implemented(name: str, milestone: str) -> None:
    err_console.print(
        f"[yellow]`skillctl {name}` is not implemented yet[/yellow] (tracked under {milestone})."
    )
    raise typer.Exit(code=2)


@app.command()
def validate(
    skill_dir: Path = typer.Argument(..., help="Path to a skill directory (contains skill.yaml + SKILL.md)."),
    namespace_aware: bool = typer.Option(
        False,
        "--namespace-aware/--standalone",
        help="Check namespace against parent dir too (use when validating in-place under skills/<namespace>/<name>).",
    ),
) -> None:
    """Validate a skill directory against the v1 standard format (spec/skill-manifest-v1.md)."""
    from skillify.validator import validate_skill_dir

    result = validate_skill_dir(skill_dir, namespace_aware=namespace_aware)
    if result.ok:
        console.print(f"[green]OK[/green] {skill_dir} is a valid skill.")
        raise typer.Exit(code=0)

    err_console.print(f"[red]FAIL[/red] {skill_dir} — {len(result.issues)} issue(s):")
    for issue in result.issues:
        err_console.print(f"  [red]•[/red] {issue.path}: {issue.message}")
    raise typer.Exit(code=1)


@app.command()
def init(
    identifier: str = typer.Argument(..., help="'<namespace>/<name>' for the new skill."),
    template: str = typer.Option("prompt", "--template", help="prompt | python"),
    dest: Path = typer.Option(Path("."), "--dest", help="Parent directory to create <namespace>/<name> under."),
) -> None:
    """Scaffold a new skill that passes `skillctl validate` out of the box (T1.1a)."""
    from skillify.cli.init_cmd import run_init

    run_init(identifier=identifier, template=template, dest=dest, console=console, err_console=err_console)


@app.command()
def doctor() -> None:
    """Check the local environment: Forgejo/devpi reachability, token, python/uv, dirs (T1.1b)."""
    from skillify.cli.doctor_cmd import run_doctor

    ok = run_doctor(console=console)
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def publish(
    skill_dir: Path = typer.Argument(Path("."), help="Skill directory to package and publish."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Package + validate but do not upload."),
) -> None:
    """Validate, package, and publish a skill as a Forgejo Release artifact (T1.3)."""
    from skillify.cli.publish_cmd import run_publish

    run_publish(skill_dir=skill_dir, dry_run=dry_run, console=console, err_console=err_console)


@app.command()
def install(
    identifier: str = typer.Argument(..., help="'<namespace>/<name>[@version]' to install."),
    target: list[str] = typer.Option(
        [], "--target", help="Agent target(s) to project into (claude/opencode/codex/aider/project). Repeatable."
    ),
    source: Optional[str] = typer.Option(
        None, "--source", help="Override artifact source URL (mainly for testing without a live Forgejo)."
    ),
) -> None:
    """Install a skill into the neutral dir and project it into agent target dirs (T1.4/T1.4a/T1.5)."""
    from skillify.cli.install_cmd import run_install

    run_install(
        identifier=identifier,
        targets=target,
        source_override=source,
        console=console,
        err_console=err_console,
    )


@app.command(name="list")
def list_cmd() -> None:
    """List locally installed skills (from ~/.skillify/locks)."""
    from skillify.cli.list_cmd import run_list

    run_list(console=console)


@app.command()
def update(
    identifier: str = typer.Argument(..., help="'<namespace>/<name>' to update to the latest available version."),
) -> None:
    """Reinstall a skill at its latest available version, keeping its recorded targets."""
    from skillify.cli.install_cmd import run_update

    run_update(identifier=identifier, console=console, err_console=err_console)


@app.command()
def remove(
    identifier: str = typer.Argument(..., help="'<namespace>/<name>' to remove."),
) -> None:
    """Remove a skill from the neutral dir and all agent projections (T1.4a)."""
    from skillify.cli.install_cmd import run_remove

    run_remove(identifier=identifier, console=console, err_console=err_console)


@app.command()
def search(query: str = typer.Argument(...)) -> None:
    """Search the Skillify index (requires the Web/index backend — T3.1)."""
    _not_implemented("search", "M3 T3.1 (FastAPI backend + Postgres index)")


if __name__ == "__main__":
    app()
