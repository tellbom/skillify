"""`skillctl publish` — validate + package + upload to Forgejo as a Release (T1.3)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from skillify.common.config import load_config
from skillify.packaging.pack import PackagingError
from skillify.publish.forgejo_client import ForgejoError
from skillify.publish.publisher import AlreadyPublishedError, PublishNotConfiguredError, publish_skill_dir


def run_publish(*, skill_dir: Path, dry_run: bool, console: Console, err_console: Console) -> None:
    cfg = load_config()

    if dry_run:
        from skillify.packaging.pack import pack_skill

        try:
            result = pack_skill(skill_dir, cfg.cache_dir / "dist")
        except PackagingError as exc:
            err_console.print("[red]publish aborted — skill failed validation:[/red]")
            for issue in exc.result.issues:
                err_console.print(f"  [red]•[/red] {issue.path}: {issue.message}")
            raise typer.Exit(code=1)
        console.print(
            f"[green]Packaged[/green] {result.namespace}/{result.name}@{result.version} "
            f"({result.file_count} files, {result.size_bytes} bytes, sha256={result.sha256[:12]}...)"
        )
        console.print(f"  tarball:  {result.tarball_path}")
        console.print(f"  checksum: {result.checksum_path}")
        console.print(f"  artifact: {result.artifact_manifest_path}")
        console.print(f"  sbom:     {result.sbom_path}")
        console.print("[yellow]--dry-run: skipping upload[/yellow]")
        raise typer.Exit(code=0)

    try:
        publish_result = publish_skill_dir(skill_dir, cfg)
    except PackagingError as exc:
        err_console.print("[red]publish aborted — skill failed validation:[/red]")
        for issue in exc.result.issues:
            err_console.print(f"  [red]•[/red] {issue.path}: {issue.message}")
        raise typer.Exit(code=1)
    except PublishNotConfiguredError:
        err_console.print(
            "[red]forgejo_url / forgejo_token not configured[/red] — set them in "
            "~/.skillify/config.yaml (or SKILLIFY_FORGEJO_URL / SKILLIFY_FORGEJO_TOKEN), "
            "or run `skillctl doctor` to see what's missing."
        )
        raise typer.Exit(code=1)
    except AlreadyPublishedError as exc:
        err_console.print(
            f"[red]{exc.org}/{exc.repo} already has a release for {exc.tag}[/red] — versions are "
            "immutable once published (PLAN.md §1); bump `version` in skill.yaml and retry."
        )
        raise typer.Exit(code=1)
    except ForgejoError as exc:
        err_console.print(f"[red]publish failed:[/red] {exc}")
        if exc.body:
            err_console.print(f"  {exc.body}")
        raise typer.Exit(code=1)

    result = publish_result.pack_result
    console.print(
        f"[green]Packaged[/green] {result.namespace}/{result.name}@{result.version} "
        f"({result.file_count} files, {result.size_bytes} bytes, sha256={result.sha256[:12]}...)"
    )
    console.print(f"  tarball:  {result.tarball_path}")
    console.print(f"  checksum: {result.checksum_path}")
    console.print(f"  artifact: {result.artifact_manifest_path}")
    console.print(f"  sbom:     {result.sbom_path}")
    action = "Recovered" if publish_result.recovered else "Published"
    console.print(
        f"[green]{action}[/green] {publish_result.org}/{publish_result.repo}@{publish_result.tag} "
        f"— {publish_result.release_html_url}"
    )
    if publish_result.index_error:
        console.print(
            f"[yellow]Note: index DB write failed (Release is still authoritative): "
            f"{publish_result.index_error}[/yellow]"
        )
