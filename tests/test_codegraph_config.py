from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillify.agent.claudecode_config import ClaudeCodeConfigError, configure_codegraph_mcp as configure_claude
from skillify.agent.opencode_config import (
    OpenCodeConfigConflict,
    OpenCodeScopePaths,
    configure_codegraph_mcp as configure_opencode,
)


def test_opencode_codegraph_config_is_dry_run_and_idempotent(tmp_path: Path) -> None:
    paths = OpenCodeScopePaths.project(tmp_path)
    assert configure_opencode(paths, dry_run=True) is True
    assert not paths.config_file.exists()
    assert configure_opencode(paths) is True
    assert configure_opencode(paths) is False
    entry = json.loads(paths.config_file.read_text())["mcp"]["codegraph_explore"]
    assert entry["command"] == ["codegraph", "serve", "--mcp"]
    assert entry["environment"]["CODEGRAPH_NO_DOWNLOAD"] == "1"
    assert entry["environment"]["CODEGRAPH_PROJECT_ROOT"] == str(tmp_path.absolute())


def test_opencode_rejects_conflicting_codegraph_owner(tmp_path: Path) -> None:
    paths = OpenCodeScopePaths.project(tmp_path)
    paths.config_root.mkdir()
    paths.config_file.write_text('{"mcp":{"codegraph_explore":{"command":["other"]}}}')
    with pytest.raises(OpenCodeConfigConflict, match="not owned"):
        configure_opencode(paths)


def test_claude_codegraph_config_is_dry_run_idempotent_and_conflict_safe(tmp_path: Path) -> None:
    assert configure_claude(tmp_path, dry_run=True) is True
    assert not (tmp_path / ".mcp.json").exists()
    assert configure_claude(tmp_path) is True
    assert configure_claude(tmp_path) is False
    entry = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]["codegraph_explore"]
    assert entry["args"] == ["serve", "--mcp"]
    assert entry["env"]["CODEGRAPH_TELEMETRY"] == "0"
    entry["command"] = "other"
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"codegraph_explore": entry}}))
    with pytest.raises(ClaudeCodeConfigError, match="another owner"):
        configure_claude(tmp_path)

