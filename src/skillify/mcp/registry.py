"""Validated MCP registry, OpenCode rendering and bounded stdio probe.

This module deliberately does not contain a gateway or a resident server.  It
validates immutable distribution metadata and probes a caller-selected local
binary using an exact argv and an explicitly supplied environment.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import InitVar, dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from skillify.agent.capability_lock import CapabilityKind
from skillify.agent.permissions import PermissionManifest, PermissionValidationError
from skillify.install.resolver import CapabilityResolveError, Coordinate


class McpRegistryError(ValueError):
    """MCP metadata is malformed, mutable, or unsafe."""


class McpTransport(str, Enum):
    STDIO = "stdio"
    REMOTE = "remote"


_ENV_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,127}\Z")
_LICENSE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]{0,63}\Z")
_HOST_RE = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")
_MAX_ARG = 4096
_MAX_ARGS = 128
_VALIDATED_ARTIFACT_TOKEN = object()
_SENSITIVE_ARG_RE = re.compile(
    r"(?:api[-_]?key|auth(?:orization)?|bearer|credential|header|password|secret|token)",
    re.IGNORECASE,
)
_ENV_REFERENCE_RE = re.compile(r"\{env:([A-Z_][A-Z0-9_]{0,127})\}\Z")
_APPROVED_CREDENTIAL_ENV_RE = re.compile(
    r"SKILLIFY_MCP_[A-Z0-9]+(?:_[A-Z0-9]+)*\Z"
)
_CREDENTIAL_FLAGS = frozenset(
    {"--api-key", "--auth-token", "--authorization", "--client-secret", "--password", "--token"}
)
_BOOLEAN_SAFE_LOCAL_FLAGS = frozenset(
    {"--no-color", "--quiet", "--read-only", "--readonly", "--stdio", "--verbose"}
)
_BOOLEAN_VALUES = frozenset({"0", "1", "false", "no", "off", "on", "true", "yes"})
_LOG_LEVELS = frozenset({"critical", "debug", "error", "info", "trace", "warning"})
_DIRECT_EXECUTABLE_CONSTRAINT = "reviewed-direct-governed-server-binary"
_CLOSED_ARGUMENT_CONSTRAINT = "approved-options-only-no-positionals"
_EXACT_ENVIRONMENT_CONSTRAINT = "exact-consumed-skillify-mcp-credential-references-only"


def _executable_family(value: str) -> str:
    executable = value.casefold()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        executable = executable.removesuffix(suffix)
    prefix_families = (("python", "python"), ("pypy", "pypy"), ("node", "node"))
    for family, prefix in prefix_families:
        if executable.startswith(prefix):
            return family
    families = (
        ("py", r"py(?:\d+(?:\.\d+)*)?[a-z]*"),
        ("uv", r"uv(?:\d+(?:\.\d+)*)?"),
        ("go", r"go(?:\d+(?:\.\d+)*)?"),
    )
    for family, pattern in families:
        if re.fullmatch(pattern, executable):
            return family
    return re.sub(r"(?:[-_.]?v?\d+(?:\.\d+)*)$", "", executable)


@dataclass(frozen=True)
class McpArtifact:
    coordinate: Coordinate
    forgejo_release: str
    commit: str
    checksum: str
    license: str
    source: str
    transport: McpTransport
    permissions: PermissionManifest
    enabled: bool
    approved_forgejo_base: str
    _validation_token: InitVar[object] = None
    command: tuple[str, ...] = ()
    environment: tuple[str, ...] = ()
    url: str | None = None
    allowed_host: str | None = None
    auth_env: str | None = None
    tls_required: bool = True
    timeout_seconds: float = 15.0

    def __post_init__(self, _validation_token: object) -> None:
        if _validation_token is not _VALIDATED_ARTIFACT_TOKEN:
            raise McpRegistryError("MCP artifacts must be created by load_mcp_artifact")

    @property
    def namespace(self) -> str:
        return self.coordinate.identifier.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.coordinate.identifier.split("/", 1)[1]


def _permissions_as_dict(value: PermissionManifest) -> dict[str, object]:
    return {
        "policyId": value.policy_id,
        "readPaths": list(value.read_paths),
        "writePaths": list(value.write_paths),
        "commands": {key: action.value for key, action in value.commands.items()},
        "networkDomains": list(value.network_domains),
        "mcpServers": list(value.mcp_servers),
        "databaseResources": list(value.database_resources),
        "unattended": value.unattended,
        "confirm": list(value.confirm),
    }


@dataclass(frozen=True)
class McpInstallPreview:
    coordinate: str
    transport: str
    source: str
    checksum: str
    license: str
    command: tuple[str, ...]
    execution_constraint: str | None
    argument_constraint: str | None
    credential_references: tuple[str, ...]
    environment_constraint: str | None
    remote_domain: str | None
    auth_reference: str | None
    permissions: Mapping[str, object]
    enabled: bool

    @classmethod
    def from_artifact(cls, artifact: McpArtifact) -> "McpInstallPreview":
        command = list(artifact.command)
        redact_next = False
        for index, argument in enumerate(command):
            sensitive_flag = any(word in argument.casefold() for word in ("token", "secret", "password", "authorization"))
            if redact_next:
                command[index] = "[REDACTED]"
                redact_next = False
            elif sensitive_flag and "=" in argument:
                command[index] = argument.split("=", 1)[0] + "=[REDACTED]"
            elif sensitive_flag:
                redact_next = True
        return cls(
            coordinate=str(artifact.coordinate),
            transport=artifact.transport.value,
            source=artifact.source,
            checksum=artifact.checksum,
            license=artifact.license,
            command=tuple(command),
            execution_constraint=(
                _DIRECT_EXECUTABLE_CONSTRAINT
                if artifact.transport is McpTransport.STDIO
                else None
            ),
            argument_constraint=(
                _CLOSED_ARGUMENT_CONSTRAINT
                if artifact.transport is McpTransport.STDIO
                else None
            ),
            credential_references=(
                artifact.environment
                if artifact.transport is McpTransport.STDIO
                else ((artifact.auth_env,) if artifact.auth_env is not None else ())
            ),
            environment_constraint=(
                _EXACT_ENVIRONMENT_CONSTRAINT
                if artifact.transport is McpTransport.STDIO
                else None
            ),
            remote_domain=artifact.allowed_host,
            auth_reference=artifact.auth_env,
            permissions=MappingProxyType(_permissions_as_dict(artifact.permissions)),
            enabled=artifact.enabled,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "coordinate": self.coordinate,
            "transport": self.transport,
            "source": self.source,
            "checksum": self.checksum,
            "license": self.license,
            "command": list(self.command),
            "executionConstraint": self.execution_constraint,
            "argumentConstraint": self.argument_constraint,
            "credentialReferences": list(self.credential_references),
            "environmentConstraint": self.environment_constraint,
            "remoteDomain": self.remote_domain,
            "authReference": self.auth_reference,
            "permissions": dict(self.permissions),
            "enabled": self.enabled,
        }


class McpRegistry:
    def __init__(self) -> None:
        self._artifacts: dict[Coordinate, McpArtifact] = {}

    def register(self, artifact: McpArtifact) -> None:
        if type(artifact) is not McpArtifact:
            raise McpRegistryError("registry accepts only validated MCP artifacts")
        coordinate = artifact.coordinate
        if coordinate in self._artifacts and self._artifacts[coordinate] != artifact:
            raise McpRegistryError(f"conflicting MCP coordinate: {coordinate}")
        self._artifacts[coordinate] = artifact

    def get(self, namespace: str, name: str, version: str) -> McpArtifact:
        try:
            coordinate = Coordinate(CapabilityKind.MCP, f"{namespace}/{name}", version)
        except CapabilityResolveError as exc:
            raise McpRegistryError(str(exc)) from exc
        try:
            return self._artifacts[coordinate]
        except KeyError as exc:
            raise McpRegistryError(f"unknown MCP coordinate: {coordinate}") from exc

    def preview(self, artifact: McpArtifact) -> McpInstallPreview:
        return McpInstallPreview.from_artifact(artifact)


def _required_text(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if type(value) is not str or not value:
        raise McpRegistryError(f"{key} must be a non-empty string")
    return value


def _validate_intranet_source(
    value: str, *, approved_forgejo_base: str, namespace: str, name: str, version: str, release: str
) -> str:
    if any(ord(character) <= 32 or ord(character) == 127 for character in value):
        raise McpRegistryError("source must be a canonical intranet URI")
    expected = (
        f"{approved_forgejo_base}/{namespace}/{name}/releases/download/{release}/"
        f"{namespace}-{name}-{version}.tar.gz"
    )
    if value != expected:
        raise McpRegistryError(
            "source must exactly match the immutable approved Forgejo intranet coordinate"
        )
    return value


def _canonical_forgejo_base(value: object) -> str:
    if type(value) is not str or not value or any(
        ord(character) <= 32 or ord(character) == 127 for character in value
    ):
        raise McpRegistryError("an explicit canonical approved Forgejo base URL is required")
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise McpRegistryError("approved Forgejo base URL must be canonical")
    host = parsed.hostname.casefold().rstrip(".")
    try:
        canonical_netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    except ValueError as exc:
        raise McpRegistryError("approved Forgejo base URL has an invalid port") from exc
    loopback_http = parsed.scheme == "http" and host in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not loopback_http:
        raise McpRegistryError("approved Forgejo base URL must use HTTPS")
    if (
        parsed.netloc != canonical_netloc
        or value.endswith("/")
        or "%" in parsed.path
        or "//" in parsed.path
        or any(part in {".", ".."} for part in PurePosixPath(parsed.path).parts)
    ):
        raise McpRegistryError("approved Forgejo base URL must be canonical")
    canonical = f"{parsed.scheme}://{canonical_netloc}{parsed.path}"
    if value != canonical:
        raise McpRegistryError("approved Forgejo base URL must be canonical")
    return canonical


def _load_common(
    data: Mapping[str, object], approved_forgejo_base: str
) -> tuple[Coordinate, str, str, str, str, str, PermissionManifest, bool]:
    if type(data.get("schemaVersion")) is not int or data.get("schemaVersion") != 1 or data.get("artifactKind") != "mcp":
        raise McpRegistryError("MCP artifact requires schemaVersion 1 and artifactKind mcp")
    namespace = _required_text(data, "namespace")
    name = _required_text(data, "name")
    version = _required_text(data, "version")
    try:
        coordinate = Coordinate(CapabilityKind.MCP, f"{namespace}/{name}", version)
    except CapabilityResolveError as exc:
        raise McpRegistryError(f"version and coordinate must be exact: {exc}") from exc
    release = _required_text(data, "forgejoRelease")
    if release != f"v{version}":
        raise McpRegistryError("forgejoRelease must equal immutable v<exact-version>")
    commit = _required_text(data, "commit")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise McpRegistryError("commit must be lowercase 40-hex")
    checksum = _required_text(data, "checksum")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise McpRegistryError("checksum must be lowercase 64-hex")
    license_name = _required_text(data, "license")
    if not _LICENSE_RE.fullmatch(license_name):
        raise McpRegistryError("license must be an SPDX-style identifier")
    source = _validate_intranet_source(
        _required_text(data, "source"),
        approved_forgejo_base=approved_forgejo_base,
        namespace=namespace,
        name=name,
        version=version,
        release=release,
    )
    if type(data.get("enabled")) is not bool:
        raise McpRegistryError("enabled must be a boolean")
    try:
        permissions = PermissionManifest.from_value(
            f"mcp-{namespace}-{name}-{version}", data.get("permissions")
        )
    except PermissionValidationError as exc:
        raise McpRegistryError(f"invalid permissions: {exc}") from exc
    return coordinate, release, commit, checksum, license_name, source, permissions, data["enabled"]  # type: ignore[return-value]


def load_mcp_artifact(
    value: object, *, approved_forgejo_base: str | None = None
) -> McpArtifact:
    if type(value) is not dict:
        raise McpRegistryError("MCP artifact metadata must be an object")
    approved_base = _canonical_forgejo_base(approved_forgejo_base)
    data: Mapping[str, object] = value
    transport_text = _required_text(data, "transport")
    try:
        transport = McpTransport(transport_text)
    except ValueError as exc:
        raise McpRegistryError("transport must be stdio or remote") from exc
    common = _load_common(data, approved_base)
    base_fields = {
        "schemaVersion", "artifactKind", "namespace", "name", "version", "forgejoRelease",
        "commit", "checksum", "license", "source", "transport", "permissions", "enabled",
    }
    if transport is McpTransport.STDIO:
        allowed = base_fields | {"command", "environment", "timeoutSeconds"}
        unknown = set(data) - allowed
        if unknown:
            raise McpRegistryError(f"unknown local MCP fields: {sorted(unknown)}")
        command = data.get("command")
        if type(command) not in {list, tuple} or not command or len(command) > _MAX_ARGS:
            raise McpRegistryError("command must be a bounded argv array")
        if any(type(arg) is not str or not arg or len(arg.encode()) > _MAX_ARG for arg in command):
            raise McpRegistryError("command argv contains an invalid argument")
        command_tuple = tuple(command)
        if not Path(command_tuple[0]).is_absolute():
            raise McpRegistryError("command executable must be an absolute argv path")
        executable_parts = PurePosixPath(command_tuple[0]).parts
        approved_prefix = ("/", "opt", "skillify", "mcp", common[0].identifier.split("/", 1)[1])
        if (
            ".." in executable_parts
            or executable_parts[: len(approved_prefix)] != approved_prefix
            or len(executable_parts) <= len(approved_prefix)
        ):
            raise McpRegistryError("command executable must be inside the governed MCP artifact")
        executable_family = _executable_family(Path(command_tuple[0]).name)
        runtime_launcher = re.fullmatch(
            r"(?:busybox|bunx|cargo|composer|corepack|curl|env|gem|npm|npx|pip|pipx|pnpm|pnpx|toybox|uv|uvx|wget|yarn)",
            executable_family,
        )
        if runtime_launcher:
            raise McpRegistryError("runtime package and download launchers are forbidden")
        interpreter = re.fullmatch(
            r"(?:bun|deno|js|lua|node(?:js)?|perl|php|py|pypy|pythonw?|ruby)",
            executable_family,
        )
        if interpreter:
            raise McpRegistryError(
                "local MCP command requires a reviewed direct governed server binary; "
                "interpreter and runtime executables are forbidden"
            )
        shell_launcher = re.fullmatch(
            r"(?:(?:ba|da|z|fi)?sh|cmd|powershell|pwsh)", executable_family
        )
        if shell_launcher or (
            len(command_tuple) >= 2 and command_tuple[1] in {"-c", "/c", "-command"}
        ):
            raise McpRegistryError("shell commands are forbidden; use exact argv")
        environment = data.get("environment")
        if type(environment) not in {list, tuple} or len(environment) > 128:
            raise McpRegistryError("environment must be a bounded name allowlist")
        if any(type(name) is not str or not _ENV_RE.fullmatch(name) for name in environment):
            raise McpRegistryError("environment must contain names, never values")
        environment_names = set(environment)
        if len(environment) != len(environment_names):
            raise McpRegistryError("environment must be a unique exact credential reference set")
        if any(
            _APPROVED_CREDENTIAL_ENV_RE.fullmatch(name) is None
            for name in environment_names
        ):
            raise McpRegistryError(
                "environment names must use the approved MCP credential namespace; "
                "loader and runtime control environment names are forbidden"
            )
        credential_reference_indexes: set[int] = set()
        credential_environment_names: set[str] = set()
        safe_value_indexes: set[int] = set()
        for index, argument in enumerate(command_tuple[1:], start=1):
            if index in credential_reference_indexes or index in safe_value_indexes:
                continue
            flag, separator, assigned = argument.partition("=")
            normalized_flag = flag.casefold()
            if normalized_flag in _CREDENTIAL_FLAGS:
                candidate = assigned if separator else (
                    command_tuple[index + 1] if index + 1 < len(command_tuple) else ""
                )
                reference = _ENV_REFERENCE_RE.fullmatch(candidate)
                if reference is None:
                    raise McpRegistryError(
                        "credential flags require an exact environment reference"
                    )
                if _APPROVED_CREDENTIAL_ENV_RE.fullmatch(reference.group(1)) is None:
                    raise McpRegistryError(
                        "credential environment references must use the approved MCP namespace; "
                        "control environment names are forbidden"
                    )
                credential_environment_names.add(reference.group(1))
                credential_reference_indexes.add(index if separator else index + 1)
                continue
            if normalized_flag in _BOOLEAN_SAFE_LOCAL_FLAGS:
                following = command_tuple[index + 1] if index + 1 < len(command_tuple) else ""
                if separator or following.casefold() in _BOOLEAN_VALUES:
                    raise McpRegistryError("boolean safety options must be exact bare tokens")
                continue
            if normalized_flag == "--log-level":
                candidate = assigned if separator else (
                    command_tuple[index + 1] if index + 1 < len(command_tuple) else ""
                )
                if candidate.casefold() not in _LOG_LEVELS:
                    raise McpRegistryError("log-level option must use an allowed value")
                if not separator:
                    safe_value_indexes.add(index + 1)
                continue
            if normalized_flag.startswith("-"):
                raise McpRegistryError(
                    "unapproved option control or runtime location in MCP argv"
                )
            if "{env:" in argument or _ENV_REFERENCE_RE.fullmatch(argument):
                if index not in credential_reference_indexes:
                    raise McpRegistryError(
                        "environment references are allowed only after explicit credential flags"
                    )
            if _SENSITIVE_ARG_RE.search(argument):
                raise McpRegistryError("secret-bearing command arguments are forbidden")
            if not normalized_flag.startswith("-"):
                raise McpRegistryError(
                    "local MCP command requires a direct governed server binary with "
                    "approved options; positional scripts and subcommands are forbidden"
                )

        if any(
            index not in credential_reference_indexes
            and ("//" in argument or re.search(r"(?i)[a-z][a-z0-9+.-]*:", argument))
            for index, argument in enumerate(command_tuple[1:], start=1)
        ):
            raise McpRegistryError("runtime download URLs are forbidden in MCP argv")
        if environment_names != credential_environment_names:
            raise McpRegistryError(
                "environment must equal the exact credential references consumed by argv"
            )
        timeout_seconds, _ = _validate_timeout(data.get("timeoutSeconds", 15))
        coordinate, release, commit, checksum, license_name, source, permissions, enabled = common
        return McpArtifact(
            coordinate=coordinate,
            forgejo_release=release,
            commit=commit,
            checksum=checksum,
            license=license_name,
            source=source,
            transport=transport,
            permissions=permissions,
            enabled=enabled,
            approved_forgejo_base=approved_base,
            _validation_token=_VALIDATED_ARTIFACT_TOKEN,
            command=command_tuple,
            environment=tuple(sorted(credential_environment_names)),
            timeout_seconds=timeout_seconds,
        )

    allowed = base_fields | {"url", "allowedHost", "authEnv", "tlsRequired", "timeoutSeconds"}
    unknown = set(data) - allowed
    if unknown:
        raise McpRegistryError(f"unknown remote MCP fields: {sorted(unknown)}")
    url = _required_text(data, "url")
    if any(ord(character) <= 32 or ord(character) == 127 for character in url):
        raise McpRegistryError("remote MCP URL must be canonical")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or "%" in parsed.path
        or "//" in parsed.path
        or any(part in {".", ".."} for part in PurePosixPath(parsed.path).parts)
    ):
        raise McpRegistryError("remote MCP url must be an absolute HTTPS URL without credentials")
    host = parsed.hostname.casefold().rstrip(".")
    allowed_host = _required_text(data, "allowedHost").casefold().rstrip(".")
    if not _HOST_RE.fullmatch(allowed_host) or host != allowed_host:
        raise McpRegistryError("remote MCP URL host must exactly match allowedHost")
    try:
        canonical_netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    except ValueError as exc:
        raise McpRegistryError("remote MCP URL has an invalid port") from exc
    if parsed.netloc != canonical_netloc:
        raise McpRegistryError("remote MCP URL and allowedHost must be canonical")
    auth_env = _required_text(data, "authEnv")
    if not _ENV_RE.fullmatch(auth_env):
        raise McpRegistryError("authEnv must be an environment reference name, never a secret")
    if data.get("tlsRequired") is not True:
        raise McpRegistryError("remote MCP requires TLS")
    timeout, _ = _validate_timeout(data.get("timeoutSeconds"))
    coordinate, release, commit, checksum, license_name, source, permissions, enabled = common
    return McpArtifact(
        coordinate=coordinate,
        forgejo_release=release,
        commit=commit,
        checksum=checksum,
        license=license_name,
        source=source,
        transport=transport,
        permissions=permissions,
        enabled=enabled,
        approved_forgejo_base=approved_base,
        _validation_token=_VALIDATED_ARTIFACT_TOKEN,
        url=url,
        allowed_host=allowed_host,
        auth_env=auth_env,
        tls_required=True,
        timeout_seconds=float(timeout),
    )


def _validate_timeout(value: object) -> tuple[float, int]:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise McpRegistryError("timeoutSeconds must be a representable millisecond value")
    try:
        decimal = Decimal(str(value))
        milliseconds = decimal * 1000
    except (InvalidOperation, ValueError) as exc:
        raise McpRegistryError("timeoutSeconds must be a representable millisecond value") from exc
    if (
        not decimal.is_finite()
        or decimal < Decimal("0.001")
        or decimal > Decimal("120")
        or milliseconds != milliseconds.to_integral_value()
    ):
        raise McpRegistryError("timeoutSeconds must be an exact value from 0.001 to 120 seconds")
    return float(decimal), int(milliseconds)


def render_opencode_mcp(artifact: McpArtifact) -> dict[str, object]:
    """Render only keys supported by the pinned OpenCode v1.15.11 MCP schema."""
    if type(artifact) is not McpArtifact:
        raise McpRegistryError("only validated MCP artifacts can be rendered")
    if artifact.transport is McpTransport.STDIO:
        rendered: dict[str, object] = {
            "type": "local", "command": list(artifact.command), "enabled": artifact.enabled,
            "timeout": _validate_timeout(artifact.timeout_seconds)[1],
        }
        if artifact.environment:
            rendered["environment"] = {name: f"{{env:{name}}}" for name in artifact.environment}
        return rendered
    return {
        "type": "remote",
        "url": artifact.url,
        "enabled": artifact.enabled,
        "headers": {"Authorization": f"Bearer {{env:{artifact.auth_env}}}"},
        "timeout": _validate_timeout(artifact.timeout_seconds)[1],
    }


def mcp_artifact_as_dict(artifact: McpArtifact) -> dict[str, object]:
    """Return canonical secret-free distribution metadata for a sidecar."""
    if type(artifact) is not McpArtifact:
        raise McpRegistryError("only validated MCP artifacts can be serialized")
    permissions = _permissions_as_dict(artifact.permissions)
    permissions.pop("policyId")
    value: dict[str, object] = {
        "schemaVersion": 1,
        "artifactKind": "mcp",
        "namespace": artifact.namespace,
        "name": artifact.name,
        "version": artifact.coordinate.version,
        "forgejoRelease": artifact.forgejo_release,
        "commit": artifact.commit,
        "checksum": artifact.checksum,
        "license": artifact.license,
        "source": artifact.source,
        "transport": artifact.transport.value,
        "permissions": permissions,
        "enabled": artifact.enabled,
    }
    if artifact.transport is McpTransport.STDIO:
        value.update(
            command=list(artifact.command),
            environment=list(artifact.environment),
            timeoutSeconds=artifact.timeout_seconds,
        )
    else:
        value.update(
            url=artifact.url,
            allowedHost=artifact.allowed_host,
            authEnv=artifact.auth_env,
            tlsRequired=artifact.tls_required,
            timeoutSeconds=artifact.timeout_seconds,
        )
    return value
