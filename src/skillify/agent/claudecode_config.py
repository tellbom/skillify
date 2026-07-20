"""Minimal Claude Code project configuration owned by Skillify."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from skillify.agent.codegraph import mcp_environment


class ClaudeCodeConfigError(RuntimeError):
    pass


def configure_codegraph_mcp(
    workspace: Path,
    *,
    executable: str = "codegraph",
    dry_run: bool = False,
) -> bool:
    root = Path(workspace).absolute()
    path = root / ".mcp.json"
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ClaudeCodeConfigError("existing .mcp.json is invalid") from exc
        if not isinstance(value, dict) or not isinstance(value.get("mcpServers", {}), dict):
            raise ClaudeCodeConfigError("existing .mcp.json must contain an mcpServers object")
    else:
        value = {}
    servers = dict(value.get("mcpServers", {}))
    desired = {
        "type": "stdio",
        "command": executable,
        "args": ["serve", "--mcp", "--path", str(root)],
        "env": mcp_environment(root),
    }
    existing = servers.get("codegraph_explore")
    if existing is not None and existing != desired:
        raise ClaudeCodeConfigError("codegraph_explore is already configured by another owner")
    if existing == desired:
        return False
    if dry_run:
        return True
    root.mkdir(parents=True, exist_ok=True)
    servers["codegraph_explore"] = desired
    value["mcpServers"] = servers
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".mcp.", suffix=".tmp", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def write_task_mcp_config(config_dir: Path, servers: dict[str, dict[str, object]]) -> Path | None:
    if not servers:
        return None
    root = Path(config_dir)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / ".mcp.json"
    content = json.dumps({"mcpServers": servers}, ensure_ascii=False, sort_keys=True) + "\n"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path
