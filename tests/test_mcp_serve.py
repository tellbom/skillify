from __future__ import annotations

import os
import sys

from typer.testing import CliRunner

from skillify.cli.main import app
from skillify.mcp.sdk_client import call_stdio_tool


def test_skillctl_mcp_serve_uses_official_sdk_stdio() -> None:
    result = call_stdio_tool(
        [sys.executable, "-m", "skillify.cli.main", "mcp", "serve", "echo"],
        request={"name": "echo", "arguments": {"text": "ready"}},
        timeout_seconds=5,
        environ=os.environ,
    )

    assert result.text == "ready"
    assert result.tools == ("echo",)


def test_skillctl_mcp_list_shows_registered_adapters() -> None:
    result = CliRunner().invoke(app, ["mcp", "list"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "catalog",
        "db-readonly",
        "documents",
        "echo",
        "forgejo",
        "rest",
    ]
