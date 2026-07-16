"""Bounded Forgejo issue and CI tools over an injected API backend."""

from __future__ import annotations

from typing import Any, Protocol
import os

import requests

from mcp.server.fastmcp import FastMCP

from skillify.mcp.scope import ConnectorPolicy, ToolAccess, ToolScope


GET_ISSUE = ToolScope("forgejo.get_issue", ToolAccess.READ, frozenset({"repo:read"}))
COMMENT_ISSUE = ToolScope("forgejo.comment_issue", ToolAccess.WRITE, frozenset({"issue:write"}))
GET_CI_STATUS = ToolScope("ci.get_status", ToolAccess.READ, frozenset({"ci:read"}))
RERUN_CI = ToolScope("ci.rerun", ToolAccess.WRITE, frozenset({"ci:write"}))


class ForgejoBackend(Protocol):
    def get_issue(self, owner: str, repository: str, number: int) -> dict[str, Any]: ...
    def comment_issue(self, owner: str, repository: str, number: int, body: str) -> dict[str, Any]: ...
    def get_ci_status(self, owner: str, repository: str, reference: str) -> dict[str, Any]: ...
    def rerun_ci(self, owner: str, repository: str, run_id: str) -> dict[str, Any]: ...


class ForgejoDevelopmentConnector:
    def __init__(self, backend: ForgejoBackend, policy: ConnectorPolicy) -> None:
        self.backend = backend
        self.policy = policy

    def get_issue(self, owner: str, repository: str, number: int) -> dict[str, Any]:
        self.policy.authorize(GET_ISSUE)
        return self.backend.get_issue(owner, repository, number)

    def comment_issue(self, owner: str, repository: str, number: int, body: str) -> dict[str, Any]:
        self.policy.authorize(COMMENT_ISSUE)
        if not body.strip() or len(body) > 4000:
            raise ValueError("issue comment must contain 1 to 4000 characters")
        return self.backend.comment_issue(owner, repository, number, body)

    def get_ci_status(self, owner: str, repository: str, reference: str) -> dict[str, Any]:
        self.policy.authorize(GET_CI_STATUS)
        return self.backend.get_ci_status(owner, repository, reference)

    def rerun_ci(self, owner: str, repository: str, run_id: str) -> dict[str, Any]:
        self.policy.authorize(RERUN_CI)
        return self.backend.rerun_ci(owner, repository, run_id)


def create_mcp_server(connector: ForgejoDevelopmentConnector) -> FastMCP:
    """Expose atomic Forgejo/CI tools without duplicating authorization logic."""
    server = FastMCP("skillify-forgejo")

    server.tool(name="forgejo.get_issue")(connector.get_issue)
    server.tool(name="forgejo.comment_issue")(connector.comment_issue)
    server.tool(name="ci.get_status")(connector.get_ci_status)
    server.tool(name="ci.rerun")(connector.rerun_ci)
    return server


class ForgejoHttpBackend:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/"); self.token = token

    def _request(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        response = requests.request(
            method, self.base_url + path, json=json,
            headers={"Authorization": f"token {self.token}"}, timeout=10,
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Forgejo response must be an object")
        return value

    def get_issue(self, owner, repository, number):
        return self._request("GET", f"/api/v1/repos/{owner}/{repository}/issues/{number}")

    def comment_issue(self, owner, repository, number, body):
        return self._request("POST", f"/api/v1/repos/{owner}/{repository}/issues/{number}/comments", {"body": body})

    def get_ci_status(self, owner, repository, reference):
        return self._request("GET", f"/api/v1/repos/{owner}/{repository}/commits/{reference}/status")

    def rerun_ci(self, owner, repository, run_id):
        return self._request("POST", f"/api/v1/repos/{owner}/{repository}/actions/runs/{run_id}/rerun")


def create_configured_server() -> FastMCP:
    scopes = frozenset(value for value in os.environ.get("SKILLIFY_MCP_FORGEJO_SCOPES", "repo:read,ci:read").split(",") if value)
    writes = frozenset(value for value in os.environ.get("SKILLIFY_MCP_FORGEJO_WRITE_TOOLS", "").split(",") if value)
    connector = ForgejoDevelopmentConnector(
        ForgejoHttpBackend(os.environ["SKILLIFY_MCP_FORGEJO_URL"], os.environ["SKILLIFY_MCP_FORGEJO_TOKEN"]),
        ConnectorPolicy(scopes, writes),
    )
    return create_mcp_server(connector)
