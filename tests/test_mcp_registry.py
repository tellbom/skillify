from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from skillify.mcp.registry import (
    McpProbeError,
    McpRegistry,
    McpRegistryError,
    McpTransport,
    load_mcp_artifact as _load_mcp_artifact,
    probe_stdio_mcp,
    render_opencode_mcp,
)


FIXTURES = Path(__file__).parent / "fixtures"
APPROVED_FORGEJO_BASE = "https://forgejo.internal"


def load_mcp_artifact(value: object):
    return _load_mcp_artifact(value, approved_forgejo_base=APPROVED_FORGEJO_BASE)


def _permissions() -> dict[str, object]:
    return {
        "readPaths": [],
        "writePaths": [],
        "commands": {},
        "networkDomains": [],
        "mcpServers": [],
        "databaseResources": [],
        "unattended": False,
        "confirm": [],
    }


def local_artifact(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "artifactKind": "mcp",
        "namespace": "approved",
        "name": "echo",
        "version": "1.2.3",
        "forgejoRelease": "v1.2.3",
        "commit": "b" * 40,
        "checksum": "a" * 64,
        "license": "MIT",
        "source": "https://forgejo.internal/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz",
        "transport": "stdio",
        "command": ["/opt/skillify/mcp/echo/bin/server"],
        "environment": ["PATH"],
        "permissions": _permissions(),
        "enabled": True,
    }
    value.update(changes)
    return value


def remote_artifact(**changes: object) -> dict[str, object]:
    value = local_artifact(
        name="remote",
        source="https://forgejo.internal/approved/remote/releases/download/v1.2.3/approved-remote-1.2.3.tar.gz",
        transport="remote",
        url="https://mcp.internal/mcp",
        allowedHost="mcp.internal",
        authEnv="MCP_TOKEN",
        tlsRequired=True,
        timeoutSeconds=15,
    )
    for key in ("command", "environment"):
        value.pop(key)
    value.update(changes)
    return value


def test_local_mcp_requires_argv_checksum_and_intranet_source() -> None:
    artifact = load_mcp_artifact(local_artifact())
    assert artifact.transport is McpTransport.STDIO
    assert artifact.coordinate.identifier == "approved/echo"


@pytest.mark.parametrize(
    "source",
    [
        "https://evil.internal/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz",
        "https://forgejo.internal/attacker/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz",
    ],
)
def test_source_must_match_explicit_approved_forgejo_base_exactly(source: str) -> None:
    with pytest.raises(McpRegistryError, match="approved Forgejo"):
        _load_mcp_artifact(local_artifact(source=source), approved_forgejo_base=APPROVED_FORGEJO_BASE)


def test_source_requires_an_explicit_approved_forgejo_base() -> None:
    with pytest.raises(McpRegistryError, match="approved Forgejo"):
        _load_mcp_artifact(local_artifact())


@pytest.mark.parametrize("command", ["python server.py", ["sh", "-c", "server"]])
def test_local_mcp_rejects_shell_commands(command: object) -> None:
    with pytest.raises(McpRegistryError, match="argv|shell"):
        load_mcp_artifact(local_artifact(command=command))


@pytest.mark.parametrize(
    "command",
    [
        ["/usr/bin/env", "sh", "server"],
        ["/usr/bin/curl", "https://public.example/server"],
        ["/usr/bin/python3", "-c", "import urllib.request"],
        ["/opt/skillify/mcp/echo/bin/npx", "-y", "remote-package"],
        ["/opt/skillify/mcp/echo/bin/uvx", "remote-package"],
        ["/opt/skillify/mcp/echo/bin/pip", "install", "remote-package"],
        ["/opt/skillify/mcp/echo/bin/python3", "-m", "pip", "install", "remote-package"],
        ["/opt/skillify/mcp/echo/bin/env", "sh", "-c", "server"],
        ["/opt/skillify/mcp/echo/bin/python3.11", "-m", "pip", "install", "package"],
        ["/opt/skillify/mcp/echo/bin/nodejs", "-e", "fetch('https://public.example')"],
        ["/opt/skillify/mcp/echo/bin/corepack", "npx", "package"],
        ["/opt/skillify/mcp/echo/bin/PIP3.11.EXE", "install", "package"],
        ["/opt/skillify/mcp/echo/bin/bash5", "-c", "server"],
        ["/opt/skillify/mcp/echo/bin/py", "-m", "pip"],
        ["/opt/skillify/mcp/echo/bin/pythonw3.11", "-m", "pip"],
        ["/opt/skillify/mcp/echo/bin/node20", "-e", "fetch('payload')"],
        ["/opt/skillify/mcp/echo/bin/server", "--download=HTTPS://public.example/archive"],
        ["/opt/skillify/mcp/echo/bin/server", "prefix=ftp://public.example/archive"],
        ["/opt/skillify/mcp/echo/bin/server", "config=file://runtime/package"],
        ["/opt/skillify/mcp/echo/bin/server", "--download=data:text/plain,payload"],
        ["/opt/skillify/mcp/echo/bin/server", "--download=//public.example/archive"],
        ["/bin/server", "--token", "literal-secret"],
        ["/bin/server", "--token=literal-secret"],
    ],
)
def test_local_mcp_rejects_indirect_shell_download_and_plaintext_secret(command: list[str]) -> None:
    with pytest.raises(McpRegistryError):
        load_mcp_artifact(local_artifact(command=command))


def test_local_mcp_allows_sensitive_environment_reference() -> None:
    artifact = load_mcp_artifact(
        local_artifact(command=["/opt/skillify/mcp/echo/bin/server", "--token", "{env:MCP_TOKEN}"], environment=["MCP_TOKEN"])
    )
    assert artifact.command[-1] == "{env:MCP_TOKEN}"


def test_local_mcp_allows_sensitive_assignment_environment_reference() -> None:
    artifact = load_mcp_artifact(local_artifact(
        command=["/opt/skillify/mcp/echo/bin/server", "--token={env:MCP_TOKEN}"],
        environment=["MCP_TOKEN"],
    ))
    assert artifact.command[-1] == "--token={env:MCP_TOKEN}"


def test_local_mcp_does_not_treat_download_env_reference_as_secret_reference() -> None:
    with pytest.raises(McpRegistryError, match="download"):
        load_mcp_artifact(local_artifact(
            command=["/opt/skillify/mcp/echo/bin/server", "--download={env:MCP_URL}"],
            environment=["MCP_URL"],
        ))


@pytest.mark.parametrize("flag", ["--download", "--url", "--source", "--registry"])
def test_local_mcp_rejects_split_runtime_location_environment_reference(flag: str) -> None:
    with pytest.raises(McpRegistryError, match="download"):
        load_mcp_artifact(local_artifact(
            command=["/opt/skillify/mcp/echo/bin/server", flag, "{env:MCP_URL}"],
            environment=["MCP_URL"],
        ))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"version": "latest"}, "exact"),
        ({"checksum": "bad"}, "checksum"),
        ({"source": "https://github.com/example/server"}, "intranet"),
        ({"source": "https://forgejo.internal/approved/echo/releases/latest/download/echo.tar.gz"}, "immutable"),
        ({"source": "https://forgejo.internal/approved/echo/releases/download/v1.2.3/approved-echo-1.2.3.tar.gz\n"}, "canonical"),
        ({"environment": ["TOKEN=secret"]}, "environment"),
    ],
)
def test_local_mcp_rejects_mutable_or_unsafe_metadata(changes: dict[str, object], message: str) -> None:
    with pytest.raises(McpRegistryError, match=message):
        load_mcp_artifact(local_artifact(**changes))


def test_remote_mcp_requires_https_and_auth_reference_not_secret() -> None:
    spec = load_mcp_artifact(remote_artifact())
    assert render_opencode_mcp(spec)["headers"] == {
        "Authorization": "Bearer {env:MCP_TOKEN}"
    }
    assert render_opencode_mcp(spec)["timeout"] == 15_000


@pytest.mark.parametrize(
    ("timeout", "milliseconds"),
    [(0.001, 1), (120, 120_000)],
)
def test_timeout_boundaries_render_positive_integer_milliseconds(timeout: float, milliseconds: int) -> None:
    remote = load_mcp_artifact(remote_artifact(timeoutSeconds=timeout))
    local = load_mcp_artifact(local_artifact(timeoutSeconds=timeout))
    assert render_opencode_mcp(remote)["timeout"] == milliseconds
    assert render_opencode_mcp(local)["timeout"] == milliseconds


@pytest.mark.parametrize("timeout", [0.0009, 0.0015, 120.001, float("nan"), float("inf")])
def test_timeout_rejects_submillisecond_or_unrepresentable_values(timeout: float) -> None:
    with pytest.raises(McpRegistryError, match="timeout"):
        load_mcp_artifact(remote_artifact(timeoutSeconds=timeout))


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "http://mcp.internal/mcp"},
        {"url": "https://other.internal/mcp"},
        {"url": "https://mcp.internal/mcp?access_token=literal-secret"},
        {"url": "https://MCP.internal/mcp"},
        {"url": "https://mcp.internal/%2e%2e/admin"},
        {"url": "https://mcp.internal/mcp\r\n"},
        {"authEnv": "actual bearer secret"},
        {"tlsRequired": False},
        {"authorization": "Bearer secret"},
    ],
)
def test_remote_mcp_rejects_unsafe_endpoint_or_literal_auth(changes: dict[str, object]) -> None:
    with pytest.raises(McpRegistryError):
        load_mcp_artifact(remote_artifact(**changes))


def test_registry_conflict_and_redacted_preview() -> None:
    registry = McpRegistry()
    artifact = load_mcp_artifact(local_artifact(
        command=["/opt/skillify/mcp/echo/bin/server", "--token", "{env:MCP_TOKEN}"],
        environment=["MCP_TOKEN"],
    ))
    registry.register(artifact)
    assert registry.get("approved", "echo", "1.2.3") == artifact
    preview = registry.preview(artifact)
    rendered = json.dumps(preview.as_dict())
    assert "secret" not in rendered
    assert "[REDACTED]" in rendered
    assert preview.checksum == "a" * 64

    with pytest.raises(McpRegistryError, match="conflicting MCP coordinate"):
        registry.register(load_mcp_artifact(local_artifact(enabled=False)))


def test_validated_artifact_cannot_be_replaced_to_bypass_loader() -> None:
    artifact = load_mcp_artifact(local_artifact())
    with pytest.raises(McpRegistryError, match="load_mcp_artifact"):
        replace(artifact, command=("/bin/sh", "-c", "curl https://public.example"))


def test_probe_local_echo_mcp_without_shell_or_network() -> None:
    result = probe_stdio_mcp(
        (sys.executable, str(FIXTURES / "mcp_echo_server.py")),
        request={"name": "echo", "arguments": {"text": "hello"}},
        timeout_seconds=2,
        environ={"PATH": os.environ.get("PATH", "")},
    )
    assert result.text == "hello"
    assert result.is_error is False


def test_filesystem_fixture_cannot_escape_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    result = probe_stdio_mcp(
        (sys.executable, str(FIXTURES / "mcp_filesystem_server.py")),
        request={"name": "read_fixture", "arguments": {"path": "../secret.txt"}},
        timeout_seconds=2,
        environ={"MCP_FIXTURE_ROOT": str(root)},
    )
    assert result.is_error is True
    assert "secret" not in result.text


@pytest.mark.parametrize("mode,code", [("malformed", "malformed-response"), ("wrong-id", "invalid-response")])
def test_probe_returns_only_stable_errors(mode: str, code: str) -> None:
    with pytest.raises(McpProbeError) as caught:
        probe_stdio_mcp(
            (sys.executable, str(FIXTURES / "mcp_echo_server.py"), mode),
            request={"name": "echo", "arguments": {"text": "top-secret"}},
            timeout_seconds=2,
            environ={},
        )
    assert caught.value.code == code
    assert "top-secret" not in str(caught.value)


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("bool-id", "invalid-response"),
        ("lone-surrogate", "malformed-response"),
        ("deep-response", "malformed-response"),
        ("duplicate-id", "malformed-response"),
    ],
)
def test_probe_rejects_adversarial_json_with_stable_codes(mode: str, code: str) -> None:
    with pytest.raises(McpProbeError) as caught:
        probe_stdio_mcp(
            (sys.executable, str(FIXTURES / "mcp_echo_server.py"), mode),
            request={"name": "echo", "arguments": {}},
            timeout_seconds=2,
            environ={},
        )
    assert caught.value.code == code


def test_probe_bounds_request_nesting_before_process_start() -> None:
    nested: object = "leaf"
    for _ in range(40):
        nested = {"next": nested}
    with pytest.raises(McpProbeError) as caught:
        probe_stdio_mcp(
            (sys.executable, str(FIXTURES / "missing-server.py")),
            request={"name": "echo", "arguments": {"nested": nested}},
            timeout_seconds=1,
            environ={},
        )
    assert caught.value.code == "invalid-request"


def test_probe_translates_lone_surrogate_request_to_stable_error() -> None:
    with pytest.raises(McpProbeError) as caught:
        probe_stdio_mcp(
            (sys.executable, str(FIXTURES / "missing-server.py")),
            request={"name": "echo", "arguments": {"text": "\ud800"}},
            timeout_seconds=1,
            environ={},
        )
    assert caught.value.code == "invalid-request"


def test_probe_timeout_is_bounded_and_safe() -> None:
    with pytest.raises(McpProbeError) as caught:
        probe_stdio_mcp(
            (sys.executable, str(FIXTURES / "mcp_echo_server.py"), "hang"),
            request={"name": "echo", "arguments": {}},
            timeout_seconds=0.05,
            environ={},
        )
    assert caught.value.code == "timeout"


def test_probe_rejects_oversized_request_before_pipe_write() -> None:
    with pytest.raises(McpProbeError) as caught:
        probe_stdio_mcp(
            (sys.executable, str(FIXTURES / "mcp_echo_server.py"), "hang"),
            request={"name": "echo", "arguments": {"text": "x" * 100_000}},
            timeout_seconds=0.05,
            environ={},
        )
    assert caught.value.code == "request-too-large"


@pytest.mark.parametrize(
    "environ",
    [{"BAD=NAME": "value"}, {"PATH": "x" * 5000}],
)
def test_probe_rejects_unbounded_or_non_name_environment(environ: dict[str, str]) -> None:
    with pytest.raises(McpProbeError) as caught:
        probe_stdio_mcp(
            (sys.executable, str(FIXTURES / "mcp_echo_server.py")),
            request={"name": "echo", "arguments": {}},
            timeout_seconds=1,
            environ=environ,
        )
    assert caught.value.code == "invalid-environment"


def test_probe_pipe_write_obeys_same_deadline_when_server_never_reads() -> None:
    started = time.monotonic()
    with pytest.raises(McpProbeError) as caught:
        probe_stdio_mcp(
            (sys.executable, str(FIXTURES / "mcp_echo_server.py"), "never-read"),
            request={"name": "echo", "arguments": {"text": "x" * 60_000}},
            timeout_seconds=0.05,
            environ={},
        )
    assert caught.value.code == "timeout"
    assert time.monotonic() - started < 1


def test_probe_sends_initialized_notification_before_tools() -> None:
    result = probe_stdio_mcp(
        (sys.executable, str(FIXTURES / "mcp_echo_server.py"), "strict-handshake"),
        request={"name": "echo", "arguments": {"text": "ready"}},
        timeout_seconds=2,
        environ={},
    )
    assert result.text == "ready"


def test_probe_rejects_nonzero_exit_after_response() -> None:
    with pytest.raises(McpProbeError) as caught:
        probe_stdio_mcp(
            (sys.executable, str(FIXTURES / "mcp_echo_server.py"), "exit-nonzero"),
            request={"name": "echo", "arguments": {"text": "ignored"}},
            timeout_seconds=2,
            environ={},
        )
    assert caught.value.code == "process-exited-nonzero"


def test_probe_cleans_descendant_group_when_leader_exits(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    with pytest.raises(McpProbeError):
        probe_stdio_mcp(
            (sys.executable, str(FIXTURES / "mcp_echo_server.py"), "descendant-exit"),
            request={"name": "echo", "arguments": {}},
            timeout_seconds=2,
            environ={"MCP_CHILD_PID_FILE": str(pid_file)},
        )
    child_pid = int(pid_file.read_text(encoding="ascii"))
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.01)
    else:
        pytest.fail("probe leaked a descendant process")
