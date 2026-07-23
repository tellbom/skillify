"""Official-SDK stdio server factories used by ``skillctl mcp serve``."""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP


ServerFactory = Callable[[], FastMCP]
_FACTORIES: dict[str, ServerFactory] = {}
_BUILTINS_LOADED = False


def _load_builtins() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    from skillify.mcp.db_readonly.connector import create_configured_server as database
    from skillify.mcp.catalog.connector import create_configured_server as catalog
    from skillify.mcp.docs.connector import create_configured_server as documents
    from skillify.mcp.forgejo.connector import create_configured_server as forgejo
    from skillify.mcp.rest.adapter import create_configured_server as rest

    _FACTORIES.update({
        "catalog": catalog, "db-readonly": database, "documents": documents,
        "forgejo": forgejo, "rest": rest,
    })
    _BUILTINS_LOADED = True


def register_server(name: str, factory: ServerFactory) -> None:
    if not name or name in _FACTORIES:
        raise ValueError(f"MCP server is already registered: {name}")
    _FACTORIES[name] = factory


def available_servers() -> tuple[str, ...]:
    _load_builtins()
    return tuple(sorted(_FACTORIES))


def create_server(name: str) -> FastMCP:
    _load_builtins()
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
