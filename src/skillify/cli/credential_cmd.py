"""Endpoint-local credential reference management."""

from __future__ import annotations

import json

import typer

from skillify.common.config import load_config
from skillify.credentials.store import EncryptedFileSecretStore


credential_app = typer.Typer(help="Manage endpoint-local credential references.", no_args_is_help=True)


def credential_store() -> EncryptedFileSecretStore:
    home = load_config().home
    return EncryptedFileSecretStore(home / "credentials.enc", home / "keys" / "credentials.key")


@credential_app.command()
def add(
    reference: str = typer.Argument(...),
    secret: str = typer.Option(..., "--secret", prompt=True, hide_input=True),
) -> None:
    credential_store().set(reference, secret)
    typer.echo(json.dumps({"reference": reference, "stored": True}))


@credential_app.command(name="list")
def list_cmd() -> None:
    typer.echo(json.dumps({"references": list(credential_store().references())}, sort_keys=True))


@credential_app.command()
def status(reference: str = typer.Argument(...)) -> None:
    exists = reference in credential_store().references()
    typer.echo(json.dumps({"reference": reference, "exists": exists}, sort_keys=True))


@credential_app.command()
def revoke(reference: str = typer.Argument(...)) -> None:
    typer.echo(json.dumps({"reference": reference, "revoked": credential_store().delete(reference)}, sort_keys=True))
