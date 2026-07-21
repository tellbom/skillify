from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol
from urllib.parse import urlsplit

from skillify.agent.events import PROVIDER_CONTRACT_VERSION, TASK_PROTOCOL_VERSION, TaskEvent, TaskState
from skillify.agent.permissions import MergedPermissions, merge_permissions

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class ModelRuntimeConfig:
    provider: str
    endpoint: str
    model: str
    allowed_endpoint_hosts: tuple[str, ...]
    credential_env_names: tuple[str, ...]

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("model endpoint port is invalid") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("model endpoint must be an absolute HTTP(S) URL without userinfo")
        if parsed.query or parsed.fragment or parsed.hostname not in self.allowed_endpoint_hosts:
            raise ValueError("model endpoint host must be allowlisted")
        if not self.provider or not self.model:
            raise ValueError("provider and model are required")
        if not self.credential_env_names or any(not _ENV_NAME.fullmatch(name) for name in self.credential_env_names):
            raise ValueError("credential environment-variable names are invalid")

    def redacted(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "endpoint_host": urlsplit(self.endpoint).hostname,
            "model": self.model,
            "credential_env_names": list(self.credential_env_names),
        }


@dataclass(frozen=True)
class ProviderCapability:
    provider: str
    provider_version: str
    provider_contract_version: int = PROVIDER_CONTRACT_VERSION
    supports_cancel: bool = True
    supports_streaming: bool = True


@dataclass(frozen=True)
class ProviderProbe:
    available: bool
    capability: ProviderCapability | None
    reason_code: str | None = None


@dataclass(frozen=True)
class ProviderStartSpec:
    workspace: Path
    allowed_paths: tuple[Path, ...]
    config_dir: Path
    runtime: ModelRuntimeConfig
    startup_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0
    source_config_path: Path | None = None
    mcp_servers: dict[str, dict[str, object]] = field(default_factory=dict)
    execution_mode: str = "single"
    preferred_cli: str | None = None
    team_policy: dict[str, object] = field(default_factory=dict)
    work_packages: tuple[dict[str, object], ...] = ()
    credential_refs: dict[str, str] = field(default_factory=dict)
    network_environment: dict[str, str] = field(default_factory=dict)
    network_allowlist: tuple[str, ...] = ()
    mcp_network_allowlist: dict[str, tuple[str, ...]] = field(default_factory=dict)
    base_commit: str = ""
    repository_root: Path | None = None
    permissions: MergedPermissions = field(default_factory=lambda: merge_permissions(()))

    def __post_init__(self) -> None:
        if not self.workspace.is_absolute() or self.workspace not in self.allowed_paths:
            raise ValueError("workspace must be an explicit allowed absolute path")
        if any(not path.is_absolute() for path in self.allowed_paths):
            raise ValueError("allowed paths must be absolute")
        if self.source_config_path is not None and not self.source_config_path.is_absolute():
            raise ValueError("source config path must be absolute")
        if not all(
            math.isfinite(value) and value > 0
            for value in (self.startup_timeout_seconds, self.shutdown_timeout_seconds)
        ):
            raise ValueError("timeouts must be positive")
        if self.execution_mode not in {"single", "delegated", "team"}:
            raise ValueError("execution mode is unsupported")
        if self.execution_mode == "team" and self.preferred_cli not in {"opencode", "claude-code"}:
            raise ValueError("team execution requires an approved preferred CLI")
        if self.execution_mode == "team" and self.base_commit and not re.fullmatch(
            r"[0-9a-f]{40}", self.base_commit
        ):
            raise ValueError("base_commit must be a 40-character hex commit SHA")
        if not isinstance(self.permissions, MergedPermissions):
            raise ValueError("task permissions must be a merged permission boundary")


@dataclass(frozen=True)
class ProviderHandle:
    handle_id: str
    provider: str
    provider_version: str
    base_url: str
    process_id: int


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    prompt: str
    task_protocol_version: int = TASK_PROTOCOL_VERSION
    timeout_seconds: float = 900.0

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.prompt.strip():
            raise ValueError("task id and prompt must be non-empty")
        if self.task_protocol_version != TASK_PROTOCOL_VERSION:
            raise ValueError("unsupported task protocol version")
        if not (math.isfinite(self.timeout_seconds) and self.timeout_seconds > 0):
            raise ValueError("task timeout must be positive")


@dataclass(frozen=True)
class ProviderSession:
    task_id: str
    session_id: str
    handle_id: str


@dataclass(frozen=True)
class ProviderResult:
    state: TaskState
    error_code: str | None = None
    message: str = ""


@dataclass(frozen=True)
class ProviderRecovery:
    status: str
    handle: ProviderHandle | None = None
    session: ProviderSession | None = None

    def __post_init__(self) -> None:
        if self.status not in {"absent", "live", "dead"}:
            raise ValueError("provider recovery status is invalid")
        if self.status == "live" and (self.handle is None or self.session is None):
            raise ValueError("live provider recovery requires handle and session")
        if self.status != "live" and (self.handle is not None or self.session is not None):
            raise ValueError("non-live provider recovery cannot carry handles")


class AgentProvider(Protocol):
    def probe(self) -> ProviderProbe: """Return local availability and capability."""
    def start(self, spec: ProviderStartSpec) -> ProviderHandle: """Start one isolated provider."""
    def create_session(self, handle: ProviderHandle, spec: TaskSpec) -> ProviderSession: """Create one task session."""
    def stream_events(self, handle: ProviderHandle, session: ProviderSession) -> Iterator[TaskEvent]: """Yield safe ordered events."""
    def cancel(self, handle: ProviderHandle, session: ProviderSession) -> ProviderResult: """Cancel one session."""
    def stop(self, handle: ProviderHandle) -> ProviderResult: """Stop and clean one provider."""
