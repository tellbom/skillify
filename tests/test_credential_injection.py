from __future__ import annotations

import json
import tempfile
from pathlib import Path

from skillify.credentials.injection import UnixSocketSecretServer, injected_environment, read_unix_socket


def test_secret_is_injected_only_into_child_environment() -> None:
    base = {"PATH": "/usr/bin"}
    value = injected_environment(base, "SKILLIFY_MCP_ORDERS_TOKEN", "top-secret")

    assert base == {"PATH": "/usr/bin"}
    assert value["SKILLIFY_MCP_ORDERS_TOKEN"] == "top-secret"
    assert "top-secret" not in json.dumps({"command": "skillctl", "args": ["mcp", "serve", "orders"]})


def test_secret_can_be_delivered_over_task_local_unix_socket() -> None:
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        path = Path(directory) / "broker.sock"
        with UnixSocketSecretServer(path, "short-lived-token"):
            assert read_unix_socket(path) == "short-lived-token"
        assert not path.exists()
