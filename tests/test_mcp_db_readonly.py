from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from skillify.mcp.db_readonly.connector import (
    QueryLimitError,
    QueryLimits,
    QueryPolicyError,
    ReadonlyDatabaseConnector,
    SQLiteReadExecutor,
)
from skillify.mcp.sdk_client import call_stdio_tool


SERVER = Path(__file__).parent / "fixtures/mcp_connector_server.py"


@pytest.fixture
def connection() -> sqlite3.Connection:
    value = sqlite3.connect(":memory:")
    value.executescript("""
        CREATE TABLE users (id INTEGER, name TEXT, email TEXT);
        CREATE TABLE secrets (id INTEGER, value TEXT);
        INSERT INTO users VALUES (1, 'Jane', 'jane@example.test');
        INSERT INTO users VALUES (2, 'Bob', 'bob@example.test');
        INSERT INTO users VALUES (3, 'Lin', 'lin@example.test');
        INSERT INTO secrets VALUES (1, 'hidden');
    """)
    return value


def _connector(connection: sqlite3.Connection, **kwargs) -> ReadonlyDatabaseConnector:
    return ReadonlyDatabaseConnector(
        SQLiteReadExecutor(connection), allowed_tables=frozenset({"users"}), **kwargs,
    )


@pytest.mark.parametrize("sql", [
    "SELECT * FROM users -- UNION SELECT value FROM secrets",
    "SELECT * FROM users; SELECT * FROM secrets",
    "DELETE FROM users",
    "SELECT * FROM users WHERE id IN (SELECT id FROM secrets)",
    "CALL export_users()",
])
def test_policy_rejects_comment_multistatement_write_subquery_escape_and_procedure(
    connection: sqlite3.Connection, sql: str,
) -> None:
    with pytest.raises(QueryPolicyError):
        _connector(connection).query(sql)


def test_select_cte_and_allowlisted_subquery_are_supported(connection: sqlite3.Connection) -> None:
    connector = _connector(connection)
    cte = connector.query(
        "WITH selected AS (SELECT id, name FROM users WHERE id <= 2) SELECT * FROM selected"
    )
    subquery = connector.query(
        "SELECT name FROM users WHERE id IN (SELECT id FROM users WHERE id = 1)"
    )
    assert cte["rowCount"] == 2
    assert subquery["rows"] == [{"name": "Jane"}]


def test_timeout_interrupts_long_running_sqlite_cte(connection: sqlite3.Connection) -> None:
    connector = _connector(
        connection,
        limits=QueryLimits(timeout_seconds=0.00001, max_rows=10, max_bytes=1000),
    )
    with pytest.raises(QueryLimitError, match="timed out"):
        connector.query(
            "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM cnt "
            "WHERE x < 100000000) SELECT sum(x) FROM cnt"
        )


def test_row_and_byte_limits_are_enforced(connection: sqlite3.Connection) -> None:
    with pytest.raises(QueryLimitError, match="row"):
        _connector(connection, limits=QueryLimits(max_rows=2, max_bytes=1000)).query(
            "SELECT id FROM users ORDER BY id"
        )
    with pytest.raises(QueryLimitError, match="byte"):
        _connector(connection, limits=QueryLimits(max_rows=10, max_bytes=5)).query(
            "SELECT name FROM users WHERE id = 1"
        )


def test_sensitive_columns_are_redacted_and_audit_id_is_returned(
    connection: sqlite3.Connection,
) -> None:
    result = _connector(connection, sensitive_columns=frozenset({"email"})).query(
        "SELECT id, email FROM users WHERE id = 1"
    )
    assert result["rows"] == [{"id": 1, "email": "[REDACTED]"}]
    assert len(result["auditId"]) == 32
    assert _connector(connection).list_tables()["tables"] == ["users"]


def test_database_policy_is_exposed_through_sdk_stdio_server() -> None:
    result = call_stdio_tool(
        [sys.executable, str(SERVER), "database"],
        request={"name": "db.query", "arguments": {"sql": "SELECT id, email FROM users"}},
        timeout_seconds=5,
    )

    assert result.is_error is False
    assert "[REDACTED]" in result.text
    assert "jane@example.test" not in result.text


def test_database_sdk_server_keeps_query_policy() -> None:
    result = call_stdio_tool(
        [sys.executable, str(SERVER), "database"],
        request={"name": "db.query", "arguments": {"sql": "DELETE FROM users"}},
        timeout_seconds=5,
    )

    assert result.is_error is True
