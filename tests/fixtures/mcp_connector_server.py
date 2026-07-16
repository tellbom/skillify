from __future__ import annotations

import sqlite3
import sys

from skillify.mcp.db_readonly.connector import (
    ReadonlyDatabaseConnector,
    SQLiteReadExecutor,
    create_mcp_server as create_database_server,
)
from skillify.mcp.docs.connector import (
    DocumentSearchConnector,
    create_mcp_server as create_documents_server,
)
from skillify.mcp.forgejo.connector import (
    ForgejoDevelopmentConnector,
    create_mcp_server as create_forgejo_server,
)
from skillify.mcp.scope import ConnectorPolicy


class FakeForgejo:
    def get_issue(self, owner, repository, number):
        return {"number": number, "title": "Fix parser", "state": "open"}

    def comment_issue(self, owner, repository, number, body):
        return {"created": True}

    def get_ci_status(self, owner, repository, reference):
        return {"reference": reference, "status": "success"}

    def rerun_ci(self, owner, repository, run_id):
        return {"queued": True}


class FakeDocuments:
    def search(self, collection, query, limit):
        return [{"collection": collection, "title": "Runbook", "snippet": query}][:limit]


def database_server():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript("""
        CREATE TABLE users (id INTEGER, name TEXT, email TEXT);
        CREATE TABLE secrets (id INTEGER, value TEXT);
        INSERT INTO users VALUES (1, 'Jane', 'jane@example.test');
        INSERT INTO secrets VALUES (1, 'hidden');
    """)
    connector = ReadonlyDatabaseConnector(
        SQLiteReadExecutor(connection),
        allowed_tables=frozenset({"users"}),
        sensitive_columns=frozenset({"email"}),
    )
    return create_database_server(connector)


def forgejo_server():
    connector = ForgejoDevelopmentConnector(
        FakeForgejo(), ConnectorPolicy(frozenset({"repo:read", "ci:read"}))
    )
    return create_forgejo_server(connector)


def documents_server():
    connector = DocumentSearchConnector(
        FakeDocuments(),
        ConnectorPolicy(frozenset({"docs:read"})),
        allowed_collections=frozenset({"engineering"}),
    )
    return create_documents_server(connector)


servers = {"database": database_server, "forgejo": forgejo_server, "documents": documents_server}
servers[sys.argv[1]]().run(transport="stdio")
