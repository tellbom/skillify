"""Collection-allowlisted internal document search tool."""

from __future__ import annotations

from typing import Any, Protocol
import os

import requests

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


class DocumentHttpBackend:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/"); self.token = token

    def search(self, collection: str, query: str, limit: int) -> list[dict[str, Any]]:
        response = requests.get(
            self.base_url + "/search", params={"collection": collection, "q": query, "limit": limit},
            headers={"Authorization": f"Bearer {self.token}"}, timeout=10,
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, list):
            raise ValueError("document search response must be a list")
        return value


def create_configured_server() -> FastMCP:
    collections = frozenset(value for value in os.environ["SKILLIFY_MCP_DOCS_COLLECTIONS"].split(",") if value)
    connector = DocumentSearchConnector(
        DocumentHttpBackend(os.environ["SKILLIFY_MCP_DOCS_URL"], os.environ["SKILLIFY_MCP_DOCS_TOKEN"]),
        ConnectorPolicy(frozenset({"docs:read"})), allowed_collections=collections,
    )
    return create_mcp_server(connector)
