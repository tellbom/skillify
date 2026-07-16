from __future__ import annotations

import os

import pytest

from skillify.mcp.db_readonly.connector import ReadonlyDatabaseConnector
from skillify.mcp.db_readonly.dm8_executor import connect_readonly


pytestmark = pytest.mark.skip(reason="requires test-env: DM8 read-only account and dialect")


def test_dm8_readonly_executor_against_real_schema() -> None:
    executor = connect_readonly(
        user=os.environ["SKILLIFY_TEST_DM8_READONLY_USER"],
        password=os.environ["SKILLIFY_TEST_DM8_READONLY_PASSWORD"],
        server=os.environ["SKILLIFY_TEST_DM8_HOST"],
        port=int(os.environ.get("SKILLIFY_TEST_DM8_PORT", "5236")),
    )
    connector = ReadonlyDatabaseConnector(
        executor,
        allowed_tables=frozenset({os.environ["SKILLIFY_TEST_DM8_TABLE"]}),
    )

    assert connector.list_tables()["tables"]
