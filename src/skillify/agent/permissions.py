"""Fail-closed endpoint capability permissions and redacted authorization audit."""

from __future__ import annotations

import fcntl
import fnmatch
import hashlib
import ipaddress
import json
import os
import re
import shlex
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PRIVILEGED_EXECUTABLES = frozenset({"doas", "pkexec", "su", "sudo", "sudoedit"})
_DESTRUCTIVE_EXECUTABLES = frozenset({"rm", "rmdir", "shred"})
_SHELL_EXECUTABLES = frozenset(
    {
        "bash", "cmd", "dash", "env", "fish", "ksh", "nice", "nohup",
        "powershell", "pwsh", "sh", "timeout", "xargs", "zsh",
    }
)


class PermissionValidationError(ValueError):
    """A stable fail-closed error for malformed or oversized policy inputs."""


_MAX_POLICIES = 64
_MAX_ENTRIES = 256
_MAX_PATTERN_LENGTH = 1024
_MAX_COMMAND_PATTERN_LENGTH = 512
_MAX_GLOB_SEGMENTS = 128
_MAX_REQUEST_PATH_LENGTH = 4096
_MAX_COMMAND_ARGUMENTS = 256
_MAX_ARGUMENT_LENGTH = 4096
_MAX_PROMPT_LENGTH = 1_048_576
_MAX_ENVIRONMENT_VALUE_LENGTH = 65_536
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_OPERATION_ORIGINS = frozenset({"local", "web"})


class PermissionAction(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"

    @property
    def restriction_rank(self) -> int:
        return {self.ALLOW: 0, self.ASK: 1, self.DENY: 2}[self]


class OperationKind(str, Enum):
    READ_PATH = "read"
    WRITE_PATH = "write"
    COMMAND = "command"
    NETWORK = "network"
    MCP = "mcp"
    DATABASE = "database"
    CREDENTIAL = "credential"


@dataclass(frozen=True)
class OperationRequest:
    kind: OperationKind
    workspace: Path
    path: str | Path | None = None
    command: tuple[str, ...] = ()
    domain: str | None = None
    mcp_server: str | None = None
    database_resource: str | None = None
    database_write: bool = False
    credential_name: str | None = None
    origin: str = "local"
    unattended: bool = False
    prompt: str | None = field(default=None, repr=False, compare=False)
    environment: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.origin) is str:
            object.__setattr__(self, "origin", self.origin.strip().casefold())
        if type(self.environment) in {dict, _MAPPING_PROXY_TYPE}:
            if len(self.environment) > _MAX_ENTRIES:
                raise PermissionValidationError(
                    "environment must be a bounded dictionary"
                )
            object.__setattr__(
                self,
                "environment",
                MappingProxyType(dict(self.environment)),
            )
        _validate_operation_request(self, require_exact_class=False)


@dataclass(frozen=True)
class PermissionDecision:
    action: PermissionAction
    matched_policy_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_permission_decision(self, require_exact_class=False)


def _bounded_optional_string(
    value: object,
    *,
    name: str,
    maximum: int,
) -> None:
    if value is not None and (
        type(value) is not str or len(value) > maximum or "\x00" in value
    ):
        raise PermissionValidationError(f"{name} must be a bounded string")


def _validate_operation_request(
    request: object,
    *,
    require_exact_class: bool,
) -> None:
    if require_exact_class and type(request) is not OperationRequest:
        raise PermissionValidationError("request must be an OperationRequest")
    try:
        kind = request.kind  # type: ignore[attr-defined]
        workspace = request.workspace  # type: ignore[attr-defined]
        path = request.path  # type: ignore[attr-defined]
        command = request.command  # type: ignore[attr-defined]
        domain = request.domain  # type: ignore[attr-defined]
        mcp_server = request.mcp_server  # type: ignore[attr-defined]
        database_resource = request.database_resource  # type: ignore[attr-defined]
        database_write = request.database_write  # type: ignore[attr-defined]
        credential_name = request.credential_name  # type: ignore[attr-defined]
        origin = request.origin  # type: ignore[attr-defined]
        unattended = request.unattended  # type: ignore[attr-defined]
        prompt = request.prompt  # type: ignore[attr-defined]
        environment = request.environment  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise PermissionValidationError("request is missing required fields") from exc
    if type(kind) is not OperationKind:
        raise PermissionValidationError("kind must be an OperationKind")
    if not isinstance(workspace, Path) or len(str(workspace)) > _MAX_REQUEST_PATH_LENGTH:
        raise PermissionValidationError("workspace path length or type is invalid")
    if path is not None and not isinstance(path, (str, Path)):
        raise PermissionValidationError("path must be a string or Path")
    if path is not None and (len(str(path)) > _MAX_REQUEST_PATH_LENGTH or "\x00" in str(path)):
        raise PermissionValidationError("request path length is invalid")
    if type(command) is not tuple:
        raise PermissionValidationError("command must be a tuple of string arguments")
    if len(command) > _MAX_COMMAND_ARGUMENTS:
        raise PermissionValidationError("command has too many arguments")
    if any(type(argument) is not str for argument in command):
        raise PermissionValidationError("command must be a tuple of string arguments")
    if any(len(argument) > _MAX_ARGUMENT_LENGTH or "\x00" in argument for argument in command):
        raise PermissionValidationError("command argument length is invalid")
    _bounded_optional_string(domain, name="domain", maximum=253)
    _bounded_optional_string(mcp_server, name="mcp_server", maximum=128)
    _bounded_optional_string(database_resource, name="database_resource", maximum=128)
    _bounded_optional_string(credential_name, name="credential_name", maximum=256)
    _bounded_optional_string(prompt, name="prompt", maximum=_MAX_PROMPT_LENGTH)
    if type(origin) is not str or origin not in _OPERATION_ORIGINS:
        raise PermissionValidationError("origin must be local or web")
    if type(database_write) is not bool or type(unattended) is not bool:
        raise PermissionValidationError("request flags must be strict booleans")
    if type(environment) is not _MAPPING_PROXY_TYPE or len(environment) > _MAX_ENTRIES:
        raise PermissionValidationError("environment must be a bounded immutable mapping")
    if any(
        type(key) is not str
        or type(value) is not str
        or len(key) > 256
        or len(value) > _MAX_ENVIRONMENT_VALUE_LENGTH
        or "\x00" in key
        or "\x00" in value
        for key, value in environment.items()
    ):
        raise PermissionValidationError("environment entries must be bounded strings")


def _validate_permission_decision(
    decision: object,
    *,
    require_exact_class: bool,
) -> None:
    if require_exact_class and type(decision) is not PermissionDecision:
        raise PermissionValidationError("decision must be a PermissionDecision")
    try:
        action = decision.action  # type: ignore[attr-defined]
        policy_ids = decision.matched_policy_ids  # type: ignore[attr-defined]
        reasons = decision.reason_codes  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise PermissionValidationError("decision is missing required fields") from exc
    if type(action) is not PermissionAction:
        raise PermissionValidationError("action must be a PermissionAction")
    if type(policy_ids) is not tuple or type(reasons) is not tuple:
        raise PermissionValidationError("decision identifiers must be tuples")
    if len(policy_ids) > _MAX_POLICIES or len(reasons) > _MAX_ENTRIES:
        raise PermissionValidationError("decision identifiers exceed resource limits")
    if any(type(item) is not str or not _IDENTIFIER_RE.fullmatch(item) for item in policy_ids):
        raise PermissionValidationError("matched policy ID is invalid")
    if any(type(item) is not str or not _IDENTIFIER_RE.fullmatch(item) for item in reasons):
        raise PermissionValidationError("reason code is invalid")


def _as_action(value: PermissionAction | str) -> PermissionAction:
    if type(value) not in {PermissionAction, str}:
        raise PermissionValidationError("permission action must be an enum or string")
    try:
        return value if isinstance(value, PermissionAction) else PermissionAction(value)
    except ValueError as exc:
        raise PermissionValidationError(f"invalid permission action: {value!r}") from exc


def _category(kind: OperationKind) -> str:
    return kind.value


def _safe_relative_pattern(pattern: str) -> bool:
    if not pattern or "\x00" in pattern or "\\" in pattern:
        return False
    if pattern == "*":
        return True
    pure = PurePosixPath(pattern)
    return not pure.is_absolute() and ".." not in pure.parts and "." not in pure.parts


def _validate_bounded_entries(
    name: str,
    entries: tuple[str, ...],
    *,
    maximum_length: int,
) -> None:
    if len(entries) > _MAX_ENTRIES:
        raise PermissionValidationError(f"{name} has too many entries")
    if any(len(item) > maximum_length or "\x00" in item for item in entries):
        raise PermissionValidationError(f"{name} entry length is invalid")


def _match_segments(pattern: str, relative_path: str) -> bool:
    if pattern == "*":
        return True
    pattern_parts = PurePosixPath(pattern).parts
    path_parts = PurePosixPath(relative_path).parts

    pending = [(0, 0)]
    visited: set[tuple[int, int]] = set()
    while pending:
        pattern_index, path_index = pending.pop()
        state = (pattern_index, path_index)
        if state in visited:
            continue
        visited.add(state)
        if pattern_index == len(pattern_parts):
            if path_index == len(path_parts):
                return True
            continue
        token = pattern_parts[pattern_index]
        if token == "**":
            pending.append((pattern_index + 1, path_index))
            if path_index < len(path_parts):
                pending.append((pattern_index, path_index + 1))
        elif path_index < len(path_parts) and fnmatch.fnmatchcase(
            path_parts[path_index], token
        ):
            pending.append((pattern_index + 1, path_index + 1))
    return False


def _resolved_relative(path: str | Path | None, workspace: Path) -> str | None:
    if path is None:
        return None
    root = workspace.resolve(strict=False)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve(strict=False).relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None


def _path_allowed(patterns: Sequence[str], path: str | Path | None, workspace: Path) -> bool:
    relative = _resolved_relative(path, workspace)
    if relative is None:
        return False
    return any(_safe_relative_pattern(pattern) and _match_segments(pattern, relative) for pattern in patterns)


def _parse_command_pattern(pattern: str) -> tuple[str, ...] | None:
    if pattern == "*":
        return ("*",)
    if not pattern or "\n" in pattern or "\r" in pattern or "\x00" in pattern:
        return None
    try:
        tokens = tuple(shlex.split(pattern, posix=True))
    except ValueError:
        return None
    return tokens or None


def _command_matches(
    pattern: str,
    argv: tuple[str, ...],
    *,
    broaden_executable: bool = False,
) -> bool:
    tokens = _parse_command_pattern(pattern)
    if not tokens or not argv:
        return False
    if tokens == ("*",):
        return True
    def token_matches(index: int, expected: str, argument: str) -> bool:
        if index == 0 and broaden_executable and "/" not in expected and "\\" not in expected:
            argument = Path(argument).name
        return fnmatch.fnmatchcase(argument, expected)

    if tokens[-1] == "*":
        prefix = tokens[:-1]
        return len(argv) >= len(prefix) and all(
            token_matches(index, expected, argument)
            for index, (expected, argument) in enumerate(zip(prefix, argv, strict=False))
        )
    return len(tokens) == len(argv) and all(
        token_matches(index, expected, argument)
        for index, (expected, argument) in enumerate(zip(tokens, argv, strict=True))
    )


def _normalize_domain(value: str) -> str | None:
    candidate = value.strip().rstrip(".")
    if not candidate or any(char.isspace() for char in candidate):
        return None
    try:
        return str(ipaddress.ip_address(candidate)).lower()
    except ValueError:
        pass
    # Several resolvers accept abbreviated, octal, decimal, or hexadecimal IPv4
    # spellings.  Treat numeric-looking non-canonical forms as invalid instead of
    # letting an allowlisted "hostname" resolve to an unexpected address.
    numeric_labels = candidate.split(".")
    if all(
        re.fullmatch(r"[0-9]+", label)
        or re.fullmatch(r"0[xX][0-9A-Fa-f]+", label)
        for label in numeric_labels
    ):
        return None
    if any(char in candidate for char in "/@?#:"):
        return None
    try:
        normalized = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    labels = normalized.split(".")
    if all(
        re.fullmatch(r"[0-9]+", label)
        or re.fullmatch(r"0[xX][0-9A-Fa-f]+", label)
        for label in labels
    ):
        return None
    if any(not label or len(label) > 63 for label in labels) or len(normalized) > 253:
        return None
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in labels):
        return None
    return normalized


def _domain_allowed(patterns: Sequence[str], domain: str | None) -> bool:
    if domain is None:
        return False
    normalized = _normalize_domain(domain)
    if normalized is None:
        return False
    for pattern in patterns:
        if pattern == "*":
            return True
        wildcard = pattern.startswith("*.")
        normalized_pattern = _normalize_domain(pattern[2:] if wildcard else pattern)
        if normalized_pattern is None:
            continue
        if wildcard:
            if normalized != normalized_pattern and normalized.endswith("." + normalized_pattern):
                return True
        elif normalized == normalized_pattern:
            return True
    return False


def _named_allowed(patterns: Sequence[str], value: str | None) -> bool:
    return value is not None and any(pattern == "*" or pattern == value for pattern in patterns)


def _more_restrictive(left: PermissionAction, right: PermissionAction) -> PermissionAction:
    return left if left.restriction_rank >= right.restriction_rank else right


@dataclass(frozen=True)
class PermissionManifest:
    policy_id: str
    read_paths: tuple[str, ...] = ()
    write_paths: tuple[str, ...] = ()
    commands: Mapping[str, PermissionAction | str] = field(default_factory=dict)
    network_domains: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    database_resources: tuple[str, ...] = ()
    unattended: bool = False
    confirm: tuple[str, ...] = ()
    legacy_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.policy_id) is not str or not _IDENTIFIER_RE.fullmatch(self.policy_id):
            raise PermissionValidationError(
                "policy_id must use 1-128 safe identifier characters"
            )
        if type(self.unattended) is not bool:
            raise PermissionValidationError("unattended must be a boolean")
        sequence_fields = {
            "readPaths": self.read_paths,
            "writePaths": self.write_paths,
            "networkDomains": self.network_domains,
            "mcpServers": self.mcp_servers,
            "databaseResources": self.database_resources,
            "confirm": self.confirm,
            "legacy permissions": self.legacy_tags,
        }
        if any(
            type(patterns) is tuple and len(patterns) > _MAX_ENTRIES
            for patterns in sequence_fields.values()
        ):
            raise PermissionValidationError("permission allowlist has too many entries")
        if any(
            not isinstance(patterns, tuple)
            or any(type(item) is not str for item in patterns)
            for patterns in sequence_fields.values()
        ):
            raise PermissionValidationError(
                "permission allowlists must be sequences of strings"
            )
        if type(self.commands) not in {dict, _MAPPING_PROXY_TYPE}:
            raise PermissionValidationError("commands must map argv patterns to actions")
        if len(self.commands) > _MAX_ENTRIES:
            raise PermissionValidationError("commands has too many entries")
        if any(
            type(pattern) is not str for pattern in self.commands
        ):
            raise PermissionValidationError("commands must map argv patterns to actions")
        for name, entries, maximum in (
            ("readPaths", self.read_paths, _MAX_PATTERN_LENGTH),
            ("writePaths", self.write_paths, _MAX_PATTERN_LENGTH),
            ("networkDomains", self.network_domains, 253),
            ("mcpServers", self.mcp_servers, 128),
            ("databaseResources", self.database_resources, 128),
            ("confirm", self.confirm, 32),
            ("legacy permissions", self.legacy_tags, _MAX_COMMAND_PATTERN_LENGTH),
        ):
            _validate_bounded_entries(name, entries, maximum_length=maximum)
        if any(len(pattern) > _MAX_COMMAND_PATTERN_LENGTH for pattern in self.commands):
            raise PermissionValidationError("command pattern length is invalid")
        converted = {pattern: _as_action(action) for pattern, action in self.commands.items()}
        object.__setattr__(self, "commands", MappingProxyType(converted))
        for name, patterns in (("readPaths", self.read_paths), ("writePaths", self.write_paths)):
            if any(not _safe_relative_pattern(pattern) for pattern in patterns):
                raise PermissionValidationError(
                    f"{name} must contain workspace-relative glob patterns"
                )
            if any(len(PurePosixPath(pattern).parts) > _MAX_GLOB_SEGMENTS for pattern in patterns):
                raise PermissionValidationError(f"{name} exceeds glob segments limit")
        if any(_parse_command_pattern(pattern) is None for pattern in converted):
            raise PermissionValidationError("commands contains an invalid argv pattern")
        if any(pattern != "*" and _normalize_domain(pattern.removeprefix("*.")) is None for pattern in self.network_domains):
            raise PermissionValidationError(
                "networkDomains contains an invalid domain pattern"
            )
        for name, patterns in (
            ("mcpServers", self.mcp_servers),
            ("databaseResources", self.database_resources),
        ):
            if any(pattern != "*" and not _IDENTIFIER_RE.fullmatch(pattern) for pattern in patterns):
                raise PermissionValidationError(f"{name} contains an invalid identifier")
        valid_categories = {kind.value for kind in OperationKind}
        if any(category not in valid_categories for category in self.confirm):
            raise PermissionValidationError(
                "confirm contains an unknown operation category"
            )

    @classmethod
    def from_value(cls, policy_id: str, value: object) -> "PermissionManifest":
        if type(value) is list:
            if len(value) > _MAX_ENTRIES:
                raise PermissionValidationError(
                    "legacy permissions has too many entries"
                )
            if all(type(item) is str and item for item in value):
                return cls(policy_id=policy_id, legacy_tags=tuple(value))
        if type(value) is not dict:
            raise PermissionValidationError(
                "permissions must be a legacy string list or structured object"
            )
        allowed_keys = {
            "readPaths", "writePaths", "commands", "networkDomains", "mcpServers",
            "databaseResources", "unattended", "confirm",
        }
        if len(value) > len(allowed_keys):
            raise PermissionValidationError("permissions contains too many keys")
        unknown = set(value) - allowed_keys
        if unknown:
            rendered = sorted(repr(key) for key in unknown)
            raise PermissionValidationError(
                f"permissions contains unknown keys: {rendered!r}"
            )
        list_keys = {
            "readPaths", "writePaths", "networkDomains", "mcpServers",
            "databaseResources", "confirm",
        }
        if any(
            key in value and type(value[key]) not in {list, tuple}
            for key in list_keys
        ):
            raise PermissionValidationError("permission allowlists must be arrays")
        if any(
            key in value and len(value[key]) > _MAX_ENTRIES
            for key in list_keys
        ):
            raise PermissionValidationError("permission allowlist has too many entries")
        if "commands" in value and type(value["commands"]) is not dict:
            raise PermissionValidationError("commands must be an object")
        if "commands" in value and len(value["commands"]) > _MAX_ENTRIES:
            raise PermissionValidationError("commands has too many entries")
        if "unattended" in value and type(value["unattended"]) is not bool:
            raise PermissionValidationError("unattended must be a boolean")
        try:
            return cls(
                policy_id=policy_id,
                read_paths=tuple(value.get("readPaths", ())),
                write_paths=tuple(value.get("writePaths", ())),
                commands=value.get("commands", {}),
                network_domains=tuple(value.get("networkDomains", ())),
                mcp_servers=tuple(value.get("mcpServers", ())),
                database_resources=tuple(value.get("databaseResources", ())),
                unattended=value.get("unattended", False),
                confirm=tuple(value.get("confirm", ())),
            )
        except (TypeError, AttributeError) as exc:
            raise PermissionValidationError(
                "permissions has an invalid structured value"
            ) from exc

    def decide(self, request: OperationRequest) -> PermissionDecision:
        _validate_operation_request(request, require_exact_class=True)
        category = _category(request.kind)
        if self.legacy_tags:
            deny_tags = {tag.removeprefix("deny:") for tag in self.legacy_tags if tag.startswith("deny:")}
            ask_tags = {tag.removeprefix("ask:") for tag in self.legacy_tags if tag.startswith("ask:")}
            ask_tags.update(tag for tag in self.legacy_tags if ":" not in tag)
            if category in deny_tags:
                action, reasons = PermissionAction.DENY, ["legacy-deny"]
            elif category in ask_tags:
                action, reasons = PermissionAction.ASK, ["legacy-confirmation"]
            else:
                action, reasons = PermissionAction.DENY, ["allowlist-miss"]
            return PermissionDecision(action, (self.policy_id,), tuple(reasons))

        allowed = False
        reasons: list[str] = []
        if request.kind is OperationKind.READ_PATH:
            allowed = _path_allowed(self.read_paths, request.path, request.workspace)
        elif request.kind is OperationKind.WRITE_PATH:
            allowed = _path_allowed(self.write_paths, request.path, request.workspace)
        elif request.kind is OperationKind.COMMAND:
            matching = [
                action for pattern, action in self.commands.items()
                if _command_matches(
                    pattern,
                    request.command,
                    broaden_executable=action is not PermissionAction.ALLOW,
                )
            ]
            if matching:
                action = max(matching, key=lambda item: item.restriction_rank)
                allowed = action is not PermissionAction.DENY
                if action is PermissionAction.ASK:
                    reasons.append("command-confirmation")
                elif action is PermissionAction.DENY:
                    reasons.append("command-deny")
            else:
                action = PermissionAction.DENY
        elif request.kind is OperationKind.NETWORK:
            allowed = _domain_allowed(self.network_domains, request.domain)
        elif request.kind is OperationKind.MCP:
            allowed = _named_allowed(self.mcp_servers, request.mcp_server)
        elif request.kind is OperationKind.DATABASE:
            allowed = _named_allowed(self.database_resources, request.database_resource)
        elif request.kind is OperationKind.CREDENTIAL:
            allowed = True

        if request.kind is not OperationKind.COMMAND:
            action = PermissionAction.ALLOW if allowed else PermissionAction.DENY
        if not allowed and not reasons:
            reasons.append("allowlist-miss")

        if category in self.confirm and action is PermissionAction.ALLOW:
            action = PermissionAction.ASK
            reasons.append("policy-confirmation")
        if request.unattended and not self.unattended and action is PermissionAction.ALLOW:
            action = PermissionAction.ASK
            reasons.append("unattended-disabled")

        if request.kind is OperationKind.COMMAND and request.command:
            executable = Path(request.command[0]).name.lower()
            dangerous_executables = (
                _DESTRUCTIVE_EXECUTABLES | _PRIVILEGED_EXECUTABLES | _SHELL_EXECUTABLES
            )
            multicall_danger = executable in {"busybox", "toybox"} and any(
                Path(argument).name.lower() in dangerous_executables
                for argument in request.command[1:]
            )
            if executable in dangerous_executables or multicall_danger:
                action = _more_restrictive(action, PermissionAction.ASK)
                reasons.append("dangerous-command")
        if request.kind is OperationKind.CREDENTIAL:
            action = _more_restrictive(action, PermissionAction.ASK)
            reasons.append("credential-confirmation")
        if request.kind is OperationKind.DATABASE and request.database_write:
            action = _more_restrictive(action, PermissionAction.ASK)
            reasons.append("database-write-confirmation")
        if (
            request.kind is OperationKind.WRITE_PATH
            and request.origin.strip().casefold() == "web"
        ):
            # S2 cannot reliably classify every code-bearing file (for example,
            # Makefile has no suffix), so the safe Web-v1 boundary confirms every
            # write at the endpoint.
            action = _more_restrictive(action, PermissionAction.ASK)
            reasons.append("web-write-confirmation")

        return PermissionDecision(action, (self.policy_id,), tuple(dict.fromkeys(reasons)))


@dataclass(frozen=True)
class MergedPermissions:
    policies: tuple[PermissionManifest, ...]

    def __post_init__(self) -> None:
        if type(self.policies) is not tuple or len(self.policies) > _MAX_POLICIES:
            raise PermissionValidationError("merged policies exceed resource limits")
        if any(type(policy) is not PermissionManifest for policy in self.policies):
            raise PermissionValidationError("merged policies contain an invalid policy")

    def decide(self, request: OperationRequest) -> PermissionDecision:
        if not self.policies:
            return PermissionDecision(PermissionAction.DENY, (), ("no-policy",))
        decisions = tuple(policy.decide(request) for policy in self.policies)
        action = max(decisions, key=lambda item: item.action.restriction_rank).action
        return PermissionDecision(
            action=action,
            matched_policy_ids=tuple(
                dict.fromkeys(policy_id for decision in decisions for policy_id in decision.matched_policy_ids)
            ),
            reason_codes=tuple(
                dict.fromkeys(reason for decision in decisions for reason in decision.reason_codes)
            ),
        )


def merge_permissions(
    policies: list[PermissionManifest] | tuple[PermissionManifest, ...],
) -> MergedPermissions:
    """Retain each policy so a later allow can never erase an earlier denial."""
    if type(policies) not in {list, tuple}:
        raise PermissionValidationError("policies must be a bounded sequence")
    if len(policies) > _MAX_POLICIES:
        raise PermissionValidationError("too many policies")
    return MergedPermissions(tuple(policies))


def _command_executables(commands: Mapping[str, PermissionAction | str]) -> list[str]:
    executables: set[str] = set()
    for pattern in commands:
        tokens = _parse_command_pattern(pattern)
        if tokens:
            executables.add("*" if tokens[0] == "*" else Path(tokens[0]).name)
    return sorted(executables)


def summarize_permissions(permissions: MergedPermissions, workspace: Path) -> dict[str, Any]:
    """Return a display-safe preflight summary without absolute paths or argv."""
    workspace.resolve(strict=False)  # validates path-like input; never serialized
    return {
        "policies": [
            {
                "policyId": policy.policy_id,
                "readPaths": list(policy.read_paths),
                "writePaths": list(policy.write_paths),
                "commandExecutables": _command_executables(policy.commands),
                "commandCategories": sorted({action.value for action in policy.commands.values()}),
                "networkDomains": list(policy.network_domains),
                "mcpServers": list(policy.mcp_servers),
                "databaseResources": list(policy.database_resources),
                "unattended": policy.unattended,
                "confirm": list(policy.confirm),
            }
            for policy in permissions.policies
        ]
    }


def redact_path(path: str | Path | None, workspace: Path) -> str:
    relative = _resolved_relative(path, workspace)
    if relative is not None:
        return relative
    try:
        resolved = str(Path(path).resolve(strict=False)) if path is not None else "<missing>"
    except (OSError, RuntimeError, ValueError):
        resolved = "<invalid>"
    digest = hashlib.sha256(resolved.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"<external:{digest}>"


def _safe_identifier(value: str | None) -> str:
    if value is not None and _IDENTIFIER_RE.fullmatch(value):
        return value
    raw = (value or "<missing>").encode("utf-8", errors="replace")
    return f"<redacted:{hashlib.sha256(raw).hexdigest()[:12]}>"


def _audit_resource(request: OperationRequest) -> dict[str, str]:
    if request.kind in {OperationKind.READ_PATH, OperationKind.WRITE_PATH}:
        return {"path": redact_path(request.path, request.workspace)}
    if request.kind is OperationKind.COMMAND:
        executable = Path(request.command[0]).name if request.command else "<missing>"
        return {"executable": _safe_identifier(executable)}
    if request.kind is OperationKind.NETWORK:
        return {"domain": _normalize_domain(request.domain or "") or "<invalid>"}
    if request.kind is OperationKind.MCP:
        return {"mcpServer": _safe_identifier(request.mcp_server)}
    if request.kind is OperationKind.DATABASE:
        return {"databaseResource": _safe_identifier(request.database_resource)}
    return {"credential": "<redacted>"}


def _open_audit_parent(audit_path: Path) -> tuple[int, str]:
    """Open/create each parent via dirfd without following path-component links."""
    if audit_path.name in {"", ".", ".."} or "\x00" in audit_path.name:
        raise ValueError("audit_path must name a file")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if audit_path.is_absolute():
        descriptor = os.open(audit_path.anchor, directory_flags)
        components = audit_path.parent.parts[1:]
    else:
        descriptor = os.open(".", directory_flags)
        components = audit_path.parent.parts
    try:
        for component in components:
            if component in {"", "."}:
                continue
            if component == "..":
                raise ValueError("audit_path may not traverse parent directories")
            try:
                os.mkdir(component, 0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            next_descriptor = os.open(component, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, audit_path.name
    except BaseException:
        os.close(descriptor)
        raise


def _open_audit_file(parent_descriptor: int, filename: str, flags: int) -> int:
    """Open an existing audit leaf or win a race-safe exclusive creation."""
    existing_flags = flags & ~os.O_CREAT
    for _ in range(16):
        try:
            return os.open(filename, existing_flags, dir_fd=parent_descriptor)
        except FileNotFoundError:
            try:
                return os.open(
                    filename,
                    flags | os.O_EXCL,
                    0o600,
                    dir_fd=parent_descriptor,
                )
            except FileExistsError:
                continue
    raise OSError("audit destination changed repeatedly during secure open")


def write_authorization_audit(
    audit_path: Path,
    *,
    task_id: str,
    request: OperationRequest,
    decision: PermissionDecision,
) -> None:
    """Append one locked JSONL record, excluding prompts, values, argv, and external paths."""
    if not isinstance(audit_path, Path) or len(str(audit_path)) > _MAX_REQUEST_PATH_LENGTH:
        raise PermissionValidationError("audit path length or type is invalid")
    if type(task_id) is not str or not _IDENTIFIER_RE.fullmatch(task_id):
        raise PermissionValidationError(
            "task_id must use 1-128 safe identifier characters"
        )
    _validate_operation_request(request, require_exact_class=True)
    _validate_permission_decision(decision, require_exact_class=True)
    record = {
        "action": decision.action.value,
        "matchedPolicyIds": list(decision.matched_policy_ids),
        "operation": request.kind.value,
        "reasonCodes": list(decision.reason_codes),
        "resource": _audit_resource(request),
        "taskId": task_id,
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "unattended": request.unattended,
    }
    encoded = (json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    flags = (
        os.O_APPEND
        | os.O_CREAT
        | os.O_WRONLY
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
    )
    flags |= getattr(os, "O_NOFOLLOW", 0)
    parent_descriptor, filename = _open_audit_parent(audit_path)
    try:
        descriptor = _open_audit_file(parent_descriptor, filename, flags)
    finally:
        os.close(parent_descriptor)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("audit destination must be a regular single-link file")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("audit append made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


__all__ = [
    "MergedPermissions", "OperationKind", "OperationRequest", "PermissionAction",
    "PermissionDecision", "PermissionManifest", "merge_permissions", "redact_path",
    "PermissionValidationError", "summarize_permissions", "write_authorization_audit",
]
