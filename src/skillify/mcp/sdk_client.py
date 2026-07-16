"""Small synchronous facade over the official MCP Python SDK."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

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
        raise McpSdkClientError("cancelled") from exc
    except McpSdkClientError:
        raise
    except Exception as exc:
        raise McpSdkClientError("sdk-error") from exc


def call_stdio_tool(
    argv: Sequence[str],
    *,
    request: Mapping[str, Any],
    timeout_seconds: float = 15,
    environ: Mapping[str, str] | None = None,
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

    return anyio.run(run)
