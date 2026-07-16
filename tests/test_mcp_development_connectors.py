from __future__ import annotations

import pytest

from skillify.mcp.docs import DocumentSearchConnector
from skillify.mcp.forgejo import ForgejoDevelopmentConnector
from skillify.mcp.scope import ConnectorPolicy


class FakeForgejo:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_issue(self, owner, repository, number):
        self.calls.append(("get_issue", owner, repository, number))
        return {"number": number, "title": "Fix parser", "state": "open"}

    def comment_issue(self, owner, repository, number, body):
        self.calls.append(("comment_issue", owner, repository, number, body))
        return {"created": True}

    def get_ci_status(self, owner, repository, reference):
        self.calls.append(("get_ci_status", owner, repository, reference))
        return {"reference": reference, "status": "success"}

    def rerun_ci(self, owner, repository, run_id):
        self.calls.append(("rerun_ci", owner, repository, run_id))
        return {"queued": True}


class FakeDocuments:
    def search(self, collection, query, limit):
        return [{"collection": collection, "title": "Runbook", "snippet": query}][:limit]


def test_forgejo_and_ci_reads_use_minimum_scopes() -> None:
    backend = FakeForgejo()
    connector = ForgejoDevelopmentConnector(
        backend,
        ConnectorPolicy(frozenset({"repo:read", "ci:read"})),
    )
    assert connector.get_issue("acme", "service", 42)["title"] == "Fix parser"
    assert connector.get_ci_status("acme", "service", "main")["status"] == "success"
    with pytest.raises(PermissionError, match="minimum scope"):
        connector.comment_issue("acme", "service", 42, "done")


def test_write_tools_require_individual_authorization() -> None:
    backend = FakeForgejo()
    scopes = frozenset({"issue:write", "ci:write"})
    read_only = ForgejoDevelopmentConnector(backend, ConnectorPolicy(scopes))
    with pytest.raises(PermissionError, match="explicit"):
        read_only.comment_issue("acme", "service", 42, "investigating")

    issue_writer = ForgejoDevelopmentConnector(
        backend,
        ConnectorPolicy(scopes, frozenset({"forgejo.comment_issue"})),
    )
    assert issue_writer.comment_issue("acme", "service", 42, "investigating") == {"created": True}
    with pytest.raises(PermissionError, match="explicit"):
        issue_writer.rerun_ci("acme", "service", "run-1")


def test_administrator_token_scopes_are_rejected() -> None:
    with pytest.raises(ValueError, match="Administrator|administrator"):
        ConnectorPolicy(frozenset({"repo:admin"}))


def test_document_search_is_read_only_and_collection_allowlisted() -> None:
    connector = DocumentSearchConnector(
        FakeDocuments(), ConnectorPolicy(frozenset({"docs:read"})),
        allowed_collections=frozenset({"engineering"}),
    )
    assert connector.search("engineering", "deploy", 5)[0]["title"] == "Runbook"
    with pytest.raises(PermissionError, match="collection"):
        connector.search("finance", "payroll")
