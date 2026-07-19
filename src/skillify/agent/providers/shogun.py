"""Thin AgentProvider adapter for the pinned external Shogun Team Runtime."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import yaml

from skillify.agent.events import (
    PROVIDER_CONTRACT_VERSION, TASK_PROTOCOL_VERSION, EventType, TaskEvent, TaskState,
)
from skillify.agent.provider import (
    AgentProvider, ProviderCapability, ProviderHandle, ProviderProbe, ProviderResult,
    ProviderSession, ProviderStartSpec, TaskSpec,
)
from skillify.agent.shogun.config_gen import GeneratedShogunConfig, generate_config
from skillify.agent.shogun.contract import COMMAND_FILE, scan_queue
from skillify.agent.shogun.distribution import (
    SHOGUN_VERSION, ShogunDistributionError, check_bundle_layout,
    check_host_dependencies, load_manifest, verify_artifact,
)
from skillify.agent.shogun.events import TeamEventMapper
from skillify.agent.shogun.lifecycle import ActiveTeam, ProcessRuntime, RuntimeControl, ShogunLifecycle


@dataclass
class _RuntimeState:
    spec: ProviderStartSpec
    generated: GeneratedShogunConfig
    team: ActiveTeam


def _atomic_yaml(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


class ShogunProvider(AgentProvider):
    def __init__(
        self,
        *,
        manifest_path: Path,
        artifact_path: Path,
        install_root: Path,
        cache_root: Path,
        runtime: RuntimeControl | None = None,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.artifact_path = Path(artifact_path)
        self.install_root = Path(install_root)
        self.cache_root = Path(cache_root)
        self.runtime = runtime or ProcessRuntime()
        self.lifecycle = ShogunLifecycle(self.runtime, self.cache_root / "active-team.lock")
        self._handles: dict[str, _RuntimeState] = {}
        self._sessions: dict[str, ProviderSession] = {}

    def probe(self) -> ProviderProbe:
        try:
            manifest = load_manifest(self.manifest_path)
            verify_artifact(self.artifact_path, manifest)
            check_bundle_layout(self.install_root, manifest)
            cli = "opencode" if check_host_dependencies("opencode").available else "claude-code"
            status = check_host_dependencies(cli)
            if not status.available:
                return ProviderProbe(False, None, "shogun-host-dependency-missing")
        except (OSError, ValueError, ShogunDistributionError):
            return ProviderProbe(False, None, "shogun-runtime-unavailable")
        return ProviderProbe(True, ProviderCapability("shogun", SHOGUN_VERSION))

    def start(self, spec: ProviderStartSpec) -> ProviderHandle:
        if spec.execution_mode != "team" or spec.preferred_cli not in {"opencode", "claude-code"}:
            raise ValueError("Shogun provider requires team execution")
        manifest = load_manifest(self.manifest_path)
        verify_artifact(self.artifact_path, manifest)
        check_bundle_layout(self.install_root, manifest)
        dependencies = check_host_dependencies(spec.preferred_cli)
        if not dependencies.available:
            raise ShogunDistributionError(dependencies.detail)
        policy = spec.team_policy
        workers = int(policy.get("max_active_workers", 2))
        generated = generate_config(
            install_root=self.install_root,
            run_dir=spec.config_dir,
            preferred_cli=spec.preferred_cli,
            worker_count=workers,
            model=spec.runtime.model,
            credential_refs=spec.credential_refs,
            endpoint_environment=spec.network_environment,
            work_packages=spec.work_packages,
            mcp_servers=spec.mcp_servers,
            network_allowlist=spec.network_allowlist,
            mcp_network_allowlist=spec.mcp_network_allowlist,
        )
        team = self.lifecycle.start(spec.config_dir.name, generated, install_root=self.install_root)
        handle_id = uuid.uuid4().hex
        handle = ProviderHandle(
            handle_id, "shogun", SHOGUN_VERSION, generated.queue_dir.as_uri(), team.pid,
        )
        self._handles[handle_id] = _RuntimeState(spec, generated, team)
        return handle

    def create_session(self, handle: ProviderHandle, spec: TaskSpec) -> ProviderSession:
        runtime = self._handles.get(handle.handle_id)
        if runtime is None:
            raise ValueError("Shogun handle is not active")
        session = ProviderSession(spec.task_id, uuid.uuid4().hex, handle.handle_id)
        command = {
            "id": spec.task_id,
            "command": spec.prompt,
            "status": "pending",
            "work_packages": list(runtime.spec.work_packages),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_yaml(runtime.generated.queue_dir / COMMAND_FILE, {"commands": [command]})
        self._sessions[session.session_id] = session
        return session

    def stream_events(
        self, handle: ProviderHandle, session: ProviderSession,
    ) -> Iterator[TaskEvent]:
        runtime = self._handles.get(handle.handle_id)
        if runtime is None or session.session_id not in self._sessions:
            raise ValueError("Shogun session is not active")
        mapper = TeamEventMapper()
        sequence = 0
        yield TaskEvent(
            session.task_id, session.session_id, "shogun", SHOGUN_VERSION,
            TASK_PROTOCOL_VERSION, PROVIDER_CONTRACT_VERSION, datetime.now(timezone.utc),
            EventType.TEAM_PREPARING, TaskState.QUEUED,
            {"sequence": sequence, "stage": "preparing"},
        )
        for _ in self.runtime.queue_states(runtime.generated.queue_dir):
            terminal = False
            for item in scan_queue(runtime.generated.queue_dir):
                event = mapper.map(
                    task_id=session.task_id, session_id=session.session_id,
                    item=item, occurred_at=datetime.now(timezone.utc),
                )
                if event is None:
                    continue
                yield event
                terminal = event.type in {
                    EventType.TEAM_COMPLETED, EventType.TEAM_FAILED, EventType.TEAM_CANCELLED,
                }
            if terminal:
                return

    def cancel(self, handle: ProviderHandle, session: ProviderSession) -> ProviderResult:
        runtime = self._handles.pop(handle.handle_id, None)
        self._sessions.pop(session.session_id, None)
        if runtime is not None:
            self.lifecycle.cancel(runtime.team)
        return ProviderResult(TaskState.CANCELLED)

    def stop(self, handle: ProviderHandle) -> ProviderResult:
        runtime = self._handles.pop(handle.handle_id, None)
        if runtime is not None:
            self.lifecycle.stop(runtime.team)
        for session_id, session in tuple(self._sessions.items()):
            if session.handle_id == handle.handle_id:
                self._sessions.pop(session_id, None)
        return ProviderResult(TaskState.SUCCEEDED)
