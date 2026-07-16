"""Minimal stdio MCP surface for bounded, evidence-only Code Map queries."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from skillify.codemap.query import QUERY_TYPES, query_graph
from skillify.codemap.store import CodeMapStore


TOOL_NAME = "query_code_map"


class CodeMapMcpServer:
    def __init__(self, path: Path) -> None:
        self.store = CodeMapStore(path)

    def handle(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if method == "initialize":
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "skillify-codemap", "version": "1.0.0"},
            }
        if method == "tools/list":
            return {"tools": [{
                "name": TOOL_NAME,
                "description": "Query Code Map metadata and file/line evidence positions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "queryType": {"type": "string", "enum": list(QUERY_TYPES)},
                        "term": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    "required": ["queryType"],
                    "additionalProperties": False,
                },
            }]}
        if method == "tools/call":
            if params.get("name") != TOOL_NAME:
                raise ValueError("unknown tool")
            arguments = params.get("arguments", {})
            if type(arguments) is not dict:
                raise ValueError("tool arguments must be an object")
            results = query_graph(
                self.store.read(), str(arguments.get("queryType", "")),
                term=str(arguments.get("term", "")), limit=arguments.get("limit", 50),
            )
            payload = {"results": results}
            return {
                "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                "structuredContent": payload,
            }
        raise ValueError(f"unsupported MCP method: {method}")


def run_stdio(path: Path, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    """Serve newline-delimited JSON-RPC until stdin closes."""
    server = CodeMapMcpServer(path)
    for line in stdin:
        request: dict[str, Any] | None = None
        try:
            request = json.loads(line)
            if type(request) is not dict:
                raise ValueError("JSON-RPC request must be an object")
            if request.get("method", "").startswith("notifications/"):
                continue
            response = {
                "jsonrpc": "2.0", "id": request.get("id"),
                "result": server.handle(request["method"], request.get("params")),
            }
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            response = {
                "jsonrpc": "2.0", "id": request.get("id") if request is not None else None,
                "error": {"code": -32602, "message": str(exc)},
            }
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()


if __name__ == "__main__":
    run_stdio(Path(".skillify/code-map.json"))
