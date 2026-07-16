from __future__ import annotations

import json
import sys
import os
import subprocess
import time


MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"

if MODE == "never-read":
    time.sleep(30)


for line in sys.stdin:
    if MODE == "hang":
        time.sleep(30)
        continue
    request = json.loads(line)
    if MODE == "descendant-exit":
        child = subprocess.Popen([
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
        ])
        with open(os.environ["MCP_CHILD_PID_FILE"], "w", encoding="ascii") as handle:
            handle.write(str(child.pid))
        raise SystemExit(7)
    if "id" not in request:
        if request.get("method") == "notifications/initialized":
            os.environ["MCP_INITIALIZED"] = "1"
            continue
        raise SystemExit(8)
    if MODE == "malformed":
        print("not-json", flush=True)
        continue
    response_id = request["id"] + 1 if MODE == "wrong-id" else request["id"]
    method = request["method"]
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "echo", "version": "1.0.0"}}
    elif method == "tools/list":
        if MODE == "strict-handshake" and os.environ.get("MCP_INITIALIZED") != "1":
            print(json.dumps({"jsonrpc": "2.0", "id": response_id, "error": {"code": -32002}}), flush=True)
            continue
        result = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
    else:
        text = request["params"]["arguments"].get("text", "")
        result = {"content": [{"type": "text", "text": text}], "isError": False}
    print(json.dumps({"jsonrpc": "2.0", "id": response_id, "result": result}), flush=True)
    if MODE == "exit-nonzero" and method == "tools/call":
        raise SystemExit(7)
