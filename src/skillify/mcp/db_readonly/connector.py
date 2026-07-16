"""SQL safety policy and a thin executor boundary for read-only database MCP tools."""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP


_COMMENT = re.compile(r"--|/\*|\*/|#")
_FORBIDDEN = re.compile(
    r"\b(?:insert|update|delete|merge|replace|upsert|create|alter|drop|truncate|grant|revoke|"
    r"call|exec|execute|begin|commit|rollback|attach|detach|vacuum|analyze|reindex|load_extension)\b",
    re.IGNORECASE,
)
_TABLE = re.compile(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE)
_CTE = re.compile(
    r"(?:\bwith\s+(?:recursive\s+)?|,)\s*([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*\([^)]*\))?\s+as\s*\(",
    re.IGNORECASE,
)


class QueryPolicyError(ValueError):
    pass


class QueryLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class QueryLimits:
    timeout_seconds: float = 5.0
    max_rows: int = 200
    max_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.max_rows < 1 or self.max_bytes < 1:
            raise ValueError("query limits must be positive")


@dataclass(frozen=True)
class RawQueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


class ReadExecutor(Protocol):
    def query(self, sql: str, *, timeout_seconds: float, fetch_rows: int) -> RawQueryResult: ...
    def table_names(self) -> tuple[str, ...]: ...


def _mask_literals(sql: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(sql):
        if sql[index] != "'":
            output.append(sql[index])
            index += 1
            continue
        output.append("''")
        index += 1
        closed = False
        while index < len(sql):
            if sql[index] == "'":
                if index + 1 < len(sql) and sql[index + 1] == "'":
                    index += 2
                    continue
                index += 1
                closed = True
                break
            index += 1
        if not closed:
            raise QueryPolicyError("SQL string literal is unterminated")
    return "".join(output)


def validate_select(sql: str, allowed_tables: frozenset[str]) -> str:
    if type(sql) is not str or not sql.strip() or len(sql) > 100_000:
        raise QueryPolicyError("SQL must be a bounded non-empty string")
    if _COMMENT.search(sql):
        raise QueryPolicyError("SQL comments are not accepted")
    if ";" in sql:
        raise QueryPolicyError("multiple statements and statement separators are not accepted")
    masked = _mask_literals(sql)
    normalized = " ".join(masked.split())
    if not re.match(r"^(?:select|with)\b", normalized, re.IGNORECASE):
        raise QueryPolicyError("only SELECT queries and SELECT CTEs are allowed")
    if _FORBIDDEN.search(normalized) or re.search(r"\bselect\s+.+\s+into\b", normalized, re.IGNORECASE):
        raise QueryPolicyError("SQL contains a forbidden operation")
    cte_names = {match.casefold() for match in _CTE.findall(normalized)}
    referenced = {match.casefold() for match in _TABLE.findall(normalized)} - cte_names
    allowed = {name.casefold() for name in allowed_tables}
    if not referenced <= allowed:
        raise QueryPolicyError("query references a table outside the allowlist")
    return sql.strip()


class SQLiteReadExecutor:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def query(self, sql: str, *, timeout_seconds: float, fetch_rows: int) -> RawQueryResult:
        deadline = time.monotonic() + timeout_seconds

        def expired() -> int:
            return int(time.monotonic() >= deadline)

        self.connection.set_progress_handler(expired, 100)
        try:
            cursor = self.connection.execute(sql)
            rows = tuple(cursor.fetchmany(fetch_rows))
            columns = tuple(item[0] for item in (cursor.description or ()))
            return RawQueryResult(columns, rows)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).casefold():
                raise QueryLimitError("query timed out") from exc
            raise
        finally:
            self.connection.set_progress_handler(None, 0)

    def table_names(self) -> tuple[str, ...]:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return tuple(str(row[0]) for row in rows)


class ReadonlyDatabaseConnector:
    def __init__(
        self,
        executor: ReadExecutor,
        *,
        allowed_tables: frozenset[str],
        sensitive_columns: frozenset[str] = frozenset(),
        limits: QueryLimits = QueryLimits(),
    ) -> None:
        if not allowed_tables:
            raise ValueError("at least one allowed table is required")
        self.executor = executor
        self.allowed_tables = allowed_tables
        self.sensitive_columns = {name.casefold() for name in sensitive_columns}
        self.limits = limits

    def list_tables(self) -> dict[str, Any]:
        available = set(self.executor.table_names())
        return {
            "auditId": uuid.uuid4().hex,
            "tables": sorted(available & set(self.allowed_tables)),
        }

    def query(self, sql: str) -> dict[str, Any]:
        validated = validate_select(sql, self.allowed_tables)
        result = self.executor.query(
            validated,
            timeout_seconds=self.limits.timeout_seconds,
            fetch_rows=self.limits.max_rows + 1,
        )
        if len(result.rows) > self.limits.max_rows:
            raise QueryLimitError("query row limit exceeded")
        rows = []
        for raw in result.rows:
            row = {
                column: "[REDACTED]" if column.casefold() in self.sensitive_columns else value
                for column, value in zip(result.columns, raw, strict=True)
            }
            rows.append(row)
        byte_count = len(json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8"))
        if byte_count > self.limits.max_bytes:
            raise QueryLimitError("query byte limit exceeded")
        return {
            "auditId": uuid.uuid4().hex,
            "columns": list(result.columns),
            "rows": rows,
            "rowCount": len(rows),
            "byteCount": byte_count,
        }


def create_mcp_server(connector: ReadonlyDatabaseConnector) -> FastMCP:
    """Expose the existing read-only policy engine through the official SDK."""
    server = FastMCP("skillify-db-readonly")

    @server.tool(name="db.list_tables")
    def list_tables() -> dict[str, Any]:
        """List tables visible through the configured read-only allowlist."""
        return connector.list_tables()

    @server.tool(name="db.query")
    def query(sql: str) -> dict[str, Any]:
        """Run one bounded SELECT query through the existing safety policy."""
        return connector.query(sql)

    return server
