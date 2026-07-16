"""Collection-allowlisted internal document search tool."""

from __future__ import annotations

from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP

from skillify.mcp.scope import ConnectorPolicy, ToolAccess, ToolScope


SEARCH_DOCUMENTS = ToolScope("docs.search", ToolAccess.READ, frozenset({"docs:read"}))


class DocumentBackend(Protocol):
    def search(self, collection: str, query: str, limit: int) -> list[dict[str, Any]]: ...


class DocumentSearchConnector:
    def __init__(
        self,
        backend: DocumentBackend,
        policy: ConnectorPolicy,
        *,
        allowed_collections: frozenset[str],
    ) -> None:
        self.backend = backend
        self.policy = policy
        self.allowed_collections = allowed_collections

    def search(self, collection: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
        self.policy.authorize(SEARCH_DOCUMENTS)
        if collection not in self.allowed_collections:
            raise PermissionError("document collection is not allowlisted")
        if not query.strip() or not 1 <= limit <= 100:
            raise ValueError("document query and limit are invalid")
        return self.backend.search(collection, query, limit)


def create_mcp_server(connector: DocumentSearchConnector) -> FastMCP:
    """Expose allowlisted document search as one read-only MCP tool."""
    server = FastMCP("skillify-documents")
    server.tool(name="docs.search")(connector.search)
    return server
