from __future__ import annotations

import json
from dataclasses import replace

import pytest

from skillify.mcp.registry import (
    McpRegistry,
    McpRegistryError,
    McpTransport,
    load_mcp_artifact as _load_mcp_artifact,
    render_opencode_mcp,
)


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
        "environment": [],
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


def test_extended_auth_network_scope_and_tool_metadata_is_backward_compatible() -> None:
    legacy = load_mcp_artifact(local_artifact())
    assert legacy.credential_ref is None
    assert legacy.network == ()

    artifact = load_mcp_artifact(local_artifact(
        auth_profile="orders-user-oidc",
        credential_ref="local://orders/current-user",
        network=[{"host": "orders.internal", "port": 8443, "protocol": "https"}],
        scopes=["orders.read"],
        tools=[{"name": "get_order", "summary": "Read one order", "contextBudget": 1200}],
    ))

    assert artifact.auth_profile == "orders-user-oidc"
    assert artifact.credential_ref == "local://orders/current-user"
    assert artifact.network[0].host == "orders.internal"
    assert artifact.scopes == ("orders.read",)
    assert artifact.tools[0].context_budget == 1200


@pytest.mark.parametrize("credential_ref", ["secret-token", "local://user:password@orders", "https://orders/token"])
def test_credential_ref_accepts_references_not_secret_values(credential_ref: str) -> None:
    with pytest.raises(McpRegistryError, match="credential_ref"):
        load_mcp_artifact(local_artifact(credential_ref=credential_ref))


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
    ("executable", "arguments"),
    [
        ("python", ["server.py"]),
        ("python3.11m", ["server.py"]),
        ("python3.11-dbg", ["pip"]),
        ("pypy", ["server.py"]),
        ("pypy3.10-v7.3.15", ["pip"]),
        ("node", ["server.js"]),
        ("node-v20.12.1", ["npm-cli.js"]),
        ("php", ["server.php"]),
        ("php8.3", ["composer.phar"]),
        ("ruby", ["server.rb"]),
        ("ruby3.3", ["bundle"]),
        ("js", ["server.js"]),
        ("js102", ["server.js"]),
        ("php8.3-zts", ["server.php"]),
        ("ruby3.3-debug", ["server.rb"]),
        ("java", ["server.class"]),
        ("dotnet", ["server.dll"]),
        ("julia", ["server.jl"]),
        ("rscript", ["server.R"]),
        ("go", ["tool", "compile", "server.go"]),
        ("unknown-runtime", ["server.opaque"]),
        ("unknown-runtime", ["tool", "compile"]),
    ],
)
def test_local_mcp_requires_direct_binary_not_interpreter_wrapped_scripts(
    executable: str, arguments: list[str]
) -> None:
    with pytest.raises(McpRegistryError, match="direct governed server binary"):
        load_mcp_artifact(local_artifact(command=[
            f"/opt/skillify/mcp/echo/bin/{executable}",
            *arguments,
        ]))


def test_local_mcp_accepts_reviewed_direct_governed_server_binary() -> None:
    artifact = load_mcp_artifact(local_artifact(command=[
        "/opt/skillify/mcp/echo/bin/server",
        "--stdio",
    ]))
    assert artifact.command[0].endswith("/bin/server")


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
        ["/opt/skillify/mcp/echo/bin/uv3", "run", "server"],
        ["/opt/skillify/mcp/echo/bin/uv", "tool", "run", "server"],
        ["/opt/skillify/mcp/echo/bin/uv", "--with", "package", "run", "server"],
        ["/opt/skillify/mcp/echo/bin/bun", "x", "package"],
        ["/opt/skillify/mcp/echo/bin/go", "run", "server.go"],
        ["/opt/skillify/mcp/echo/bin/pypy3.10-v7.3.15", "-m", "pip"],
        ["/opt/skillify/mcp/echo/bin/python3.11m", "-m", "pip"],
        ["/opt/skillify/mcp/echo/bin/python3.11d", "-c", "payload"],
        ["/opt/skillify/mcp/echo/bin/node-v20.12.1", "-e", "payload"],
        ["/opt/skillify/mcp/echo/bin/python3.11-dbg", "-m", "pip"],
        ["/opt/skillify/mcp/echo/bin/node20-debug", "-e", "payload"],
        ["/opt/skillify/mcp/echo/bin/server", "--registry-url", "internal.example/index"],
        ["/opt/skillify/mcp/echo/bin/server", "--downloadURL", "internal.example/archive"],
        ["/opt/skillify/mcp/echo/bin/server", "--registryUrl", "internal.example/index"],
        ["/opt/skillify/mcp/echo/bin/server", "--repositoryURL", "internal.example/repo"],
        ["/opt/skillify/mcp/echo/bin/server", "--indexURL", "internal.example/simple"],
        ["/opt/skillify/mcp/echo/bin/server", "-i", "internal.example/simple"],
        ["/opt/skillify/mcp/echo/bin/server", "--proxy", "internal.example"],
        ["/opt/skillify/mcp/echo/bin/server", "--upstream", "internal.example"],
        ["/opt/skillify/mcp/echo/bin/server", "--host", "internal.example"],
        ["/opt/skillify/mcp/echo/bin/server", "--origin", "internal.example"],
        ["/bin/server", "--token", "literal-secret"],
        ["/bin/server", "--token=literal-secret"],
    ],
)
def test_local_mcp_rejects_indirect_shell_download_and_plaintext_secret(command: list[str]) -> None:
    with pytest.raises(McpRegistryError):
        load_mcp_artifact(local_artifact(command=command))


def test_local_mcp_allows_sensitive_environment_reference() -> None:
    artifact = load_mcp_artifact(
        local_artifact(command=["/opt/skillify/mcp/echo/bin/server", "--token", "{env:SKILLIFY_MCP_TOKEN}"], environment=["SKILLIFY_MCP_TOKEN"])
    )
    assert artifact.command[-1] == "{env:SKILLIFY_MCP_TOKEN}"


def test_local_mcp_allows_sensitive_assignment_environment_reference() -> None:
    artifact = load_mcp_artifact(local_artifact(
        command=["/opt/skillify/mcp/echo/bin/server", "--token={env:SKILLIFY_MCP_TOKEN}"],
        environment=["SKILLIFY_MCP_TOKEN"],
    ))
    assert artifact.command[-1] == "--token={env:SKILLIFY_MCP_TOKEN}"


def test_local_mcp_does_not_treat_download_env_reference_as_secret_reference() -> None:
    with pytest.raises(McpRegistryError, match="location"):
        load_mcp_artifact(local_artifact(
            command=["/opt/skillify/mcp/echo/bin/server", "--download={env:SKILLIFY_MCP_URL}"],
            environment=["SKILLIFY_MCP_URL"],
        ))


@pytest.mark.parametrize("flag", ["--download", "--url", "--source", "--registry"])
def test_local_mcp_rejects_split_runtime_location_environment_reference(flag: str) -> None:
    with pytest.raises(McpRegistryError, match="location"):
        load_mcp_artifact(local_artifact(
            command=["/opt/skillify/mcp/echo/bin/server", flag, "{env:SKILLIFY_MCP_URL}"],
            environment=["SKILLIFY_MCP_URL"],
        ))


@pytest.mark.parametrize(
    "flag",
    ["--token", "--api-key", "--password", "--auth-token", "--client-secret"],
)
@pytest.mark.parametrize("assignment", [False, True])
def test_local_mcp_allows_only_explicit_credential_environment_flags(
    flag: str, assignment: bool
) -> None:
    command = ["/opt/skillify/mcp/echo/bin/server"]
    if assignment:
        command.append(f"{flag}={{env:SKILLIFY_MCP_CREDENTIAL}}")
    else:
        command.extend([flag, "{env:SKILLIFY_MCP_CREDENTIAL}"])
    artifact = load_mcp_artifact(local_artifact(
        command=command, environment=["SKILLIFY_MCP_CREDENTIAL"]
    ))
    assert artifact.environment == ("SKILLIFY_MCP_CREDENTIAL",)
    assert render_opencode_mcp(artifact)["environment"] == {
        "SKILLIFY_MCP_CREDENTIAL": "{env:SKILLIFY_MCP_CREDENTIAL}"
    }


@pytest.mark.parametrize(
    "name",
    [
        "LD_PRELOAD",
        "DYLD_INSERT_LIBRARIES",
        "PYTHONPATH",
        "NODE_OPTIONS",
        "JAVA_TOOL_OPTIONS",
        "RUBYOPT",
        "PERL5OPT",
        "BASH_ENV",
        "ENV",
        "IFS",
        "PATH",
        "_JAVA_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "CLASSPATH",
        "DOTNET_STARTUP_HOOKS",
        "RUBYLIB",
        "LUA_PATH",
        "LUA_CPATH",
        "GEM_HOME",
        "BUNDLE_GEMFILE",
        "GLIBC_TUNABLES",
        "HTTPS_PROXY",
        "SSLKEYLOGFILE",
    ],
)
def test_local_mcp_rejects_control_environment_even_when_credential_referenced(
    name: str,
) -> None:
    with pytest.raises(McpRegistryError, match="control environment"):
        load_mcp_artifact(local_artifact(
            command=["/opt/skillify/mcp/echo/bin/server", "--token", f"{{env:{name}}}"],
            environment=[name],
        ))


@pytest.mark.parametrize(
    "name",
    [
        "SKILLIFY_MCP_",
        "SKILLIFY_MCP__TOKEN",
        "SKILLIFY_MCP_TOKEN_",
        "SKILLIFY_MCP_token",
        "SKILLIFY_MCP_TÖKEN",
        "SKILLIFY_MCP_" + "A" * 116,
    ],
)
def test_local_mcp_rejects_noncanonical_credential_environment_names(name: str) -> None:
    with pytest.raises(McpRegistryError, match="environment|credential"):
        load_mcp_artifact(local_artifact(
            command=["/opt/skillify/mcp/echo/bin/server", "--token", f"{{env:{name}}}"],
            environment=[name],
        ))


@pytest.mark.parametrize(
    ("command", "environment"),
    [
        (["/opt/skillify/mcp/echo/bin/server"], ["EXTRA_UNUSED"]),
        (
            ["/opt/skillify/mcp/echo/bin/server", "--token", "{env:SKILLIFY_MCP_TOKEN}"],
            ["SKILLIFY_MCP_TOKEN", "EXTRA_UNUSED"],
        ),
        (
            ["/opt/skillify/mcp/echo/bin/server", "--token={env:SKILLIFY_MCP_TOKEN}"],
            ["SKILLIFY_MCP_TOKEN", "SKILLIFY_MCP_TOKEN"],
        ),
        (
            ["/opt/skillify/mcp/echo/bin/server", "--token", "{env:SKILLIFY_MCP_TOKEN}"],
            ["OTHER_TOKEN"],
        ),
    ],
)
def test_local_mcp_environment_must_exactly_equal_consumed_credential_refs(
    command: list[str], environment: list[str]
) -> None:
    with pytest.raises(McpRegistryError, match="environment|credential"):
        load_mcp_artifact(local_artifact(command=command, environment=environment))


def test_local_mcp_allows_only_explicit_safe_non_location_options() -> None:
    artifact = load_mcp_artifact(local_artifact(command=[
        "/opt/skillify/mcp/echo/bin/server",
        "--stdio",
        "--read-only",
        "--log-level=info",
    ]))
    assert artifact.command[-1] == "--log-level=info"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--read-only=false"],
        ["--read-only", "false"],
        ["--stdio=false"],
        ["--stdio", "false"],
        ["--no-color=false"],
        ["--quiet=false"],
        ["--log-level"],
        ["--log-level=download"],
        ["--log-level", "download"],
    ],
)
def test_local_mcp_rejects_noncanonical_safe_option_shapes(arguments: list[str]) -> None:
    with pytest.raises(McpRegistryError, match="option"):
        load_mcp_artifact(local_artifact(command=[
            "/opt/skillify/mcp/echo/bin/server",
            *arguments,
        ]))


def test_local_mcp_allows_bounded_split_log_level() -> None:
    artifact = load_mcp_artifact(local_artifact(command=[
        "/opt/skillify/mcp/echo/bin/server",
        "--log-level",
        "warning",
    ]))
    assert artifact.command[-2:] == ("--log-level", "warning")


@pytest.mark.parametrize(
    "command",
    [
        ["/opt/skillify/mcp/echo/bin/server", "-u", "{env:SKILLIFY_MCP_LOCATION}"],
        ["/opt/skillify/mcp/echo/bin/server", "--repository", "{env:SKILLIFY_MCP_LOCATION}"],
        ["/opt/skillify/mcp/echo/bin/server", "--mode", "download", "{env:SKILLIFY_MCP_LOCATION}"],
        ["/opt/skillify/mcp/echo/bin/server", "{env:SKILLIFY_MCP_LOCATION}"],
        ["/opt/skillify/mcp/echo/bin/server", "--config={env:SKILLIFY_MCP_LOCATION}"],
    ],
)
def test_local_mcp_rejects_environment_references_outside_credential_flags(
    command: list[str],
) -> None:
    with pytest.raises(McpRegistryError, match="environment reference|location|option"):
        load_mcp_artifact(local_artifact(command=command, environment=["SKILLIFY_MCP_LOCATION"]))


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
        command=["/opt/skillify/mcp/echo/bin/server", "--token", "{env:SKILLIFY_MCP_TOKEN}"],
        environment=["SKILLIFY_MCP_TOKEN"],
    ))
    registry.register(artifact)
    assert registry.get("approved", "echo", "1.2.3") == artifact
    preview = registry.preview(artifact)
    rendered = json.dumps(preview.as_dict())
    assert "secret" not in rendered
    assert "[REDACTED]" in rendered
    assert preview.checksum == "a" * 64
    assert preview.as_dict()["executionConstraint"] == "reviewed-direct-governed-server-binary"
    assert preview.as_dict()["argumentConstraint"] == "approved-options-only-no-positionals"
    assert preview.as_dict()["credentialReferences"] == ["SKILLIFY_MCP_TOKEN"]
    assert preview.as_dict()["environmentConstraint"] == (
        "exact-consumed-skillify-mcp-credential-references-only"
    )

    with pytest.raises(McpRegistryError, match="conflicting MCP coordinate"):
        registry.register(load_mcp_artifact(local_artifact(enabled=False)))


def test_validated_artifact_cannot_be_replaced_to_bypass_loader() -> None:
    artifact = load_mcp_artifact(local_artifact())
    with pytest.raises(McpRegistryError, match="load_mcp_artifact"):
        replace(artifact, command=("/bin/sh", "-c", "curl https://public.example"))
