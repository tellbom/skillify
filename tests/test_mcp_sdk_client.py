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


def test_sdk_client_cancels_bounded_call() -> None:
    with pytest.raises(McpSdkClientError, match="cancelled") as caught:
        call_stdio_tool(
            [sys.executable, str(SERVER)],
            request={"name": "wait", "arguments": {"seconds": 30}},
            timeout_seconds=0.2,
        )

    assert caught.value.code == "cancelled"
