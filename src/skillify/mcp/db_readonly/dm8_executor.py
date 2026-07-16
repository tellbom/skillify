"""DM8 implementation of the read-only connector executor boundary."""

from __future__ import annotations

import time
from typing import Any

from skillify.mcp.db_readonly.connector import QueryLimitError, RawQueryResult


class DM8ReadExecutor:
    """Execute already-policy-validated SELECT statements with a read-only DM8 account."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def query(self, sql: str, *, timeout_seconds: float, fetch_rows: int) -> RawQueryResult:
        cursor = self.connection.cursor()
        started = time.monotonic()
        try:
            cursor.execute(sql)
            if time.monotonic() - started > timeout_seconds:
                raise QueryLimitError("query timed out")
            rows = tuple(tuple(row) for row in cursor.fetchmany(fetch_rows))
            columns = tuple(str(item[0]) for item in (cursor.description or ()))
            return RawQueryResult(columns, rows)
        finally:
            cursor.close()

    def table_names(self) -> tuple[str, ...]:
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT TABLE_NAME FROM USER_TABLES ORDER BY TABLE_NAME")
            return tuple(str(row[0]) for row in cursor.fetchall())
        finally:
            cursor.close()


def connect_readonly(*, user: str, password: str, server: str, port: int) -> DM8ReadExecutor:
    """Create an executor without importing the Linux-only DM8 driver at module load time."""
    import dmPython  # type: ignore[import-not-found]

    connection = dmPython.connect(user=user, password=password, server=server, port=port)
    return DM8ReadExecutor(connection)
