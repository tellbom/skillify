"""Official-SDK stdio server factories used by ``skillctl mcp serve``."""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP


ServerFactory = Callable[[], FastMCP]
_FACTORIES: dict[str, ServerFactory] = {}


def register_server(name: str, factory: ServerFactory) -> None:
    if not name or name in _FACTORIES:
        raise ValueError(f"MCP server is already registered: {name}")
    _FACTORIES[name] = factory


def available_servers() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def create_server(name: str) -> FastMCP:
    try:
        return _FACTORIES[name]()
    except KeyError as exc:
        raise KeyError(f"unknown MCP server: {name}") from exc


def _echo_server() -> FastMCP:
    server = FastMCP("skillify-echo")

    @server.tool()
    def echo(text: str) -> str:
        """Return text unchanged for local SDK diagnostics."""
        return text

    return server


register_server("echo", _echo_server)
