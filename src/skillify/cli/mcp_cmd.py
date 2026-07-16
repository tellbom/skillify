"""MCP SDK server and diagnostic commands."""

from __future__ import annotations

import os
import sys

import typer

from skillify.mcp.sdk_client import McpSdkClientError, call_stdio_tool
from skillify.mcp.server import available_servers, create_server


mcp_app = typer.Typer(help="Serve and inspect governed endpoint MCP adapters.", no_args_is_help=True)


@mcp_app.command()
def serve(name: str = typer.Argument(..., help="Registered MCP adapter name.")) -> None:
    """Run one registered adapter over SDK stdio transport."""
    try:
        server = create_server(name)
    except KeyError as exc:
        raise typer.BadParameter(str(exc), param_hint="name") from exc
    server.run(transport="stdio")


@mcp_app.command(name="list")
def list_cmd() -> None:
    """List adapters available to this endpoint installation."""
    for name in available_servers():
        typer.echo(name)


@mcp_app.command()
def probe(
    name: str = typer.Argument(..., help="Registered MCP adapter name."),
    tool: str = typer.Option("echo", "--tool", help="Tool to call."),
) -> None:
    """Run a bounded SDK handshake and tool call against a local adapter."""
    argv = [sys.executable, "-m", "skillify.cli.main", "mcp", "serve", name]
    try:
        result = call_stdio_tool(
            argv,
            request={"name": tool, "arguments": {"text": "probe"}},
            timeout_seconds=10,
            environ=os.environ,
        )
    except McpSdkClientError as exc:
        typer.echo(exc.code, err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.text)
