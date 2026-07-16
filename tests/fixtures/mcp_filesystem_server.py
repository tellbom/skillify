from __future__ import annotations

import json
import os
import sys
from pathlib import Path


root = Path(os.environ["MCP_FIXTURE_ROOT"]).resolve(strict=True)

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request and request.get("method") == "notifications/initialized":
        continue
    method = request["method"]
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "filesystem", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "read_fixture", "inputSchema": {"type": "object"}}]}
    else:
        try:
            candidate = (root / request["params"]["arguments"]["path"]).resolve(strict=True)
            candidate.relative_to(root)
            if not candidate.is_file():
                raise ValueError
            result = {"content": [{"type": "text", "text": candidate.read_text(encoding="utf-8")}], "isError": False}
        except (OSError, ValueError):
            result = {"content": [{"type": "text", "text": "access-denied"}], "isError": True}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
