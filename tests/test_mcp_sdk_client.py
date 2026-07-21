from __future__ import annotations

import sys
from pathlib import Path

import pytest

from skillify.mcp.sdk_client import McpSdkClientError, call_stdio_tool


SERVER = Path(__file__).parent / "fixtures/mcp_echo_server.py"


def test_sdk_client_initializes_lists_and_calls_stdio_server() -> None:
    result = call_stdio_tool(
        [sys.executable, str(SERVER)],
        request={"name": "echo", "arguments": {"text": "hello"}},
        timeout_seconds=5,
    )

    assert result.text == "hello"
    assert result.is_error is False
    assert result.tools == ("echo", "wait")


def test_sdk_client_reports_bounded_timeout_to_task_audit() -> None:
    class Audit:
        events = []

        def record(self, event_type, reason_code):
            self.events.append((event_type, reason_code))

    audit = Audit()
    with pytest.raises(McpSdkClientError, match="timeout") as caught:
        call_stdio_tool(
            [sys.executable, str(SERVER)],
            request={"name": "wait", "arguments": {"seconds": 30}},
            timeout_seconds=0.2,
            audit_sink=audit,
        )

    assert caught.value.code == "timeout"
    assert audit.events == [("mcp.adapter.timeout", "timeout")]
