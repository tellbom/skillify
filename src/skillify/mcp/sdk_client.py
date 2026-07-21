"""Small synchronous facade over the official MCP Python SDK."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Protocol, Sequence

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


class McpSdkClientError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class McpSdkResult:
    text: str
    is_error: bool
    tools: tuple[str, ...]


class McpAuditSink(Protocol):
    def record(self, event_type: str, reason_code: str) -> None: ...


_AUDIT_EVENT = {
    "cancelled": "mcp.adapter.cancelled",
    "timeout": "mcp.adapter.timeout",
    "permission-denied": "mcp.adapter.permission_denied",
    "unreachable": "mcp.adapter.unreachable",
    "crashed": "mcp.adapter.crashed",
}


def _tool_error_code(text: str) -> str:
    normalized = text.casefold()
    if "permission-denied" in normalized or "permission denied" in normalized or "403" in normalized:
        return "permission-denied"
    if "unreachable" in normalized or "connection refused" in normalized:
        return "unreachable"
    if "cancelled" in normalized or "canceled" in normalized:
        return "cancelled"
    if "timeout" in normalized or "timed out" in normalized:
        return "timeout"
    return "crashed"


async def _call_stdio_tool(
    argv: Sequence[str],
    request: Mapping[str, Any],
    timeout_seconds: float,
    environ: Mapping[str, str],
) -> McpSdkResult:
    parameters = StdioServerParameters(
        command=argv[0], args=list(argv[1:]), env=dict(environ)
    )
    try:
        with anyio.fail_after(timeout_seconds):
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=timeout_seconds),
                ) as session:
                    await session.initialize()
                    available = await session.list_tools()
                    tools = tuple(tool.name for tool in available.tools)
                    if request["name"] not in tools:
                        raise McpSdkClientError("tool-not-found")
                    result = await session.call_tool(
                        request["name"], arguments=dict(request["arguments"])
                    )
                    text = "\n".join(
                        item.text for item in result.content if isinstance(item, TextContent)
                    )
                    if not text:
                        raise McpSdkClientError("invalid-tool-result")
                    return McpSdkResult(text, bool(result.isError), tools)
    except TimeoutError as exc:
        raise McpSdkClientError("timeout") from exc
    except (FileNotFoundError, ConnectionError) as exc:
        raise McpSdkClientError("unreachable") from exc
    except McpSdkClientError:
        raise
    except Exception as exc:
        raise McpSdkClientError("crashed") from exc


def call_stdio_tool(
    argv: Sequence[str],
    *,
    request: Mapping[str, Any],
    timeout_seconds: float = 15,
    environ: Mapping[str, str] | None = None,
    audit_sink: McpAuditSink | None = None,
) -> McpSdkResult:
    if not argv or not all(isinstance(value, str) and value for value in argv):
        raise McpSdkClientError("invalid-argv")
    if (
        set(request) != {"name", "arguments"}
        or not isinstance(request.get("name"), str)
        or not isinstance(request.get("arguments"), dict)
    ):
        raise McpSdkClientError("invalid-request")
    if not 0 < timeout_seconds <= 120:
        raise McpSdkClientError("invalid-timeout")

    async def run() -> McpSdkResult:
        return await _call_stdio_tool(argv, request, timeout_seconds, environ or {})

    try:
        result = anyio.run(run)
    except McpSdkClientError as exc:
        if audit_sink is not None and exc.code in _AUDIT_EVENT:
            audit_sink.record(_AUDIT_EVENT[exc.code], exc.code)
        raise
    if result.is_error and audit_sink is not None:
        code = _tool_error_code(result.text)
        audit_sink.record(_AUDIT_EVENT[code], code)
    return result
