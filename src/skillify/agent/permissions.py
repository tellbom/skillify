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
from typing import Any, Mapping, Sequence


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PRIVILEGED_EXECUTABLES = frozenset({"doas", "pkexec", "su", "sudo", "sudoedit"})
_DESTRUCTIVE_EXECUTABLES = frozenset({"rm", "rmdir", "shred"})
_SHELL_EXECUTABLES = frozenset(
    {
        "bash", "cmd", "dash", "env", "fish", "ksh", "nice", "nohup",
        "powershell", "pwsh", "sh", "timeout", "xargs", "zsh",
    }
)


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


@dataclass(frozen=True)
class PermissionDecision:
    action: PermissionAction
    matched_policy_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]


def _as_action(value: PermissionAction | str) -> PermissionAction:
    try:
        return value if isinstance(value, PermissionAction) else PermissionAction(value)
    except ValueError as exc:
        raise ValueError(f"invalid permission action: {value!r}") from exc


def _category(kind: OperationKind) -> str:
    return kind.value


def _safe_relative_pattern(pattern: str) -> bool:
    if not pattern or "\x00" in pattern or "\\" in pattern:
        return False
    if pattern == "*":
        return True
    pure = PurePosixPath(pattern)
    return not pure.is_absolute() and ".." not in pure.parts and "." not in pure.parts


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
        if not _IDENTIFIER_RE.fullmatch(self.policy_id):
            raise ValueError("policy_id must use 1-128 safe identifier characters")
        if type(self.unattended) is not bool:
            raise ValueError("unattended must be a boolean")
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
            not isinstance(patterns, tuple)
            or any(not isinstance(item, str) for item in patterns)
            for patterns in sequence_fields.values()
        ):
            raise ValueError("permission allowlists must be sequences of strings")
        if not isinstance(self.commands, Mapping) or any(
            not isinstance(pattern, str) for pattern in self.commands
        ):
            raise ValueError("commands must map argv patterns to actions")
        converted = {pattern: _as_action(action) for pattern, action in self.commands.items()}
        object.__setattr__(self, "commands", MappingProxyType(converted))
        for name, patterns in (("readPaths", self.read_paths), ("writePaths", self.write_paths)):
            if any(not _safe_relative_pattern(pattern) for pattern in patterns):
                raise ValueError(f"{name} must contain workspace-relative glob patterns")
        if any(_parse_command_pattern(pattern) is None for pattern in converted):
            raise ValueError("commands contains an invalid argv pattern")
        if any(pattern != "*" and _normalize_domain(pattern.removeprefix("*.")) is None for pattern in self.network_domains):
            raise ValueError("networkDomains contains an invalid domain pattern")
        for name, patterns in (
            ("mcpServers", self.mcp_servers),
            ("databaseResources", self.database_resources),
        ):
            if any(pattern != "*" and not _IDENTIFIER_RE.fullmatch(pattern) for pattern in patterns):
                raise ValueError(f"{name} contains an invalid identifier")
        valid_categories = {kind.value for kind in OperationKind}
        if any(category not in valid_categories for category in self.confirm):
            raise ValueError("confirm contains an unknown operation category")

    @classmethod
    def from_value(cls, policy_id: str, value: object) -> "PermissionManifest":
        if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
            return cls(policy_id=policy_id, legacy_tags=tuple(value))
        if not isinstance(value, Mapping):
            raise ValueError("permissions must be a legacy string list or structured object")
        allowed_keys = {
            "readPaths", "writePaths", "commands", "networkDomains", "mcpServers",
            "databaseResources", "unattended", "confirm",
        }
        unknown = set(value) - allowed_keys
        if unknown:
            rendered = sorted(repr(key) for key in unknown)
            raise ValueError(f"permissions contains unknown keys: {rendered!r}")
        list_keys = {
            "readPaths", "writePaths", "networkDomains", "mcpServers",
            "databaseResources", "confirm",
        }
        if any(key in value and not isinstance(value[key], (list, tuple)) for key in list_keys):
            raise ValueError("permission allowlists must be arrays")
        if "commands" in value and not isinstance(value["commands"], Mapping):
            raise ValueError("commands must be an object")
        if "unattended" in value and type(value["unattended"]) is not bool:
            raise ValueError("unattended must be a boolean")
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
            raise ValueError("permissions has an invalid structured value") from exc

    def decide(self, request: OperationRequest) -> PermissionDecision:
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
            if executable in (
                _DESTRUCTIVE_EXECUTABLES | _PRIVILEGED_EXECUTABLES | _SHELL_EXECUTABLES
            ):
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


def merge_permissions(policies: Sequence[PermissionManifest]) -> MergedPermissions:
    """Retain each policy so a later allow can never erase an earlier denial."""
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
    if not _IDENTIFIER_RE.fullmatch(task_id):
        raise ValueError("task_id must use 1-128 safe identifier characters")
    for policy_id in decision.matched_policy_ids:
        if not _IDENTIFIER_RE.fullmatch(policy_id):
            raise ValueError("matched policy ID is invalid")
    for reason in decision.reason_codes:
        if not _IDENTIFIER_RE.fullmatch(reason):
            raise ValueError("reason code is invalid")
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
    "summarize_permissions", "write_authorization_audit",
]
