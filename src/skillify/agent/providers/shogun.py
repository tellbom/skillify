"""Thin AgentProvider adapter for the pinned external Shogun Team Runtime."""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import yaml

from skillify.agent.events import (
    PROVIDER_CONTRACT_VERSION, TASK_PROTOCOL_VERSION, EventType, TaskEvent, TaskState,
)
from skillify.agent.provider import (
    AgentProvider, ProviderCapability, ProviderHandle, ProviderProbe, ProviderResult,
    ProviderRecovery, ProviderSession, ProviderStartSpec, TaskSpec,
)
from skillify.agent.shogun.config_gen import GeneratedShogunConfig, generate_config
from skillify.agent.shogun.contract import scan_queue
from skillify.agent.shogun.distribution import (
    SHOGUN_VERSION, ShogunDistributionError, check_bundle_layout,
    check_host_dependencies, load_manifest, require_installable, verify_artifact,
)
from skillify.agent.shogun.events import TeamEventMapper
from skillify.agent.shogun.credentials import (
    CredentialBrokerLike, InjectionChannel, PaneCredentialInjector,
)
from skillify.agent.shogun.lifecycle import (
    ActiveTeam, ProcessRuntime, RuntimeControl, ShogunLifecycle, TeamHandle,
)
from skillify.agent.shogun.registry import RegistryError, WorktreeRegistry
from skillify.agent.shogun.team_recovery import RecoveryDiagnosis, diagnose
from skillify.agent.shogun.worktree import WorktreeManager, WorkerSpec


@dataclass
class _RuntimeState:
    spec: ProviderStartSpec | None
    generated: GeneratedShogunConfig
    team: ActiveTeam
    credential_channel: InjectionChannel | None = None


def _atomic_yaml(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _write_recovery_state(run_dir: Path, diagnosis: RecoveryDiagnosis) -> None:
    payload = {
        "status": diagnosis.status,
        "detail": diagnosis.detail,
        "interrupted_worktrees": list(diagnosis.interrupted_worktrees),
    }
    path = run_dir / "recovery-state.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _diagnose_worktree_state(run_dir: Path) -> RecoveryDiagnosis | None:
    """Reconcile git-worktree/merge state for teams using the git-worktree
    feature, and record the result to ``recovery-state.json``.

    Returns ``None`` (and writes nothing) if ``run_dir`` has no
    ``worktree-registry.json`` -- i.e. this team does not use the
    git-worktree feature -- so callers that don't use it are completely
    unaffected. See ``team_recovery.diagnose`` for the reconciliation logic
    itself; this function only locates the registry, invokes it, and
    persists the result.
    """
    registry_path = run_dir / "worktree-registry.json"
    if not registry_path.exists():
        return None
    merge_plan_path = run_dir / "merge-plan.json"
    try:
        repository_root = WorktreeRegistry.read(registry_path).repository_root
    except (OSError, ValueError, RegistryError, json.JSONDecodeError):
        # The registry itself is unreadable/invalid; diagnose() will detect
        # and report this as "corrupt" on its own re-read. repository_root
        # is irrelevant in that case (no live git state will be inspected).
        repository_root = run_dir
    diagnosis = diagnose(
        repository_root=repository_root,
        registry_path=registry_path,
        merge_plan_path=merge_plan_path if merge_plan_path.exists() else None,
        worktree_manager=WorktreeManager(),
    )
    _write_recovery_state(run_dir, diagnosis)
    return diagnosis


class ShogunProvider(AgentProvider):
    provider_version = SHOGUN_VERSION

    def __init__(
        self,
        *,
        manifest_path: Path,
        artifact_path: Path,
        install_root: Path,
        cache_root: Path,
        runtime: RuntimeControl | None = None,
        credential_broker: CredentialBrokerLike | None = None,
        credential_injector: PaneCredentialInjector | None = None,
        state_root: Path | None = None,
        monotonic=time.monotonic,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.artifact_path = Path(artifact_path)
        self.install_root = Path(install_root)
        self.cache_root = Path(cache_root)
        self.state_root = Path(state_root) if state_root is not None else self.cache_root / "teams"
        self.runtime = runtime or ProcessRuntime()
        self.credential_broker = credential_broker
        self.credential_injector = credential_injector or PaneCredentialInjector()
        self.monotonic = monotonic
        self.lifecycle = ShogunLifecycle(self.runtime, self.cache_root / "active-team.lock")
        self._handles: dict[str, _RuntimeState] = {}
        self._sessions: dict[str, ProviderSession] = {}

    def probe(self) -> ProviderProbe:
        try:
            manifest = load_manifest(self.manifest_path)
            require_installable(manifest)
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
        if set(spec.credential_refs) != set(spec.runtime.credential_env_names):
            raise ValueError("Shogun requires one credential reference per approved model environment name")
        manifest = load_manifest(self.manifest_path)
        require_installable(manifest)
        verify_artifact(self.artifact_path, manifest)
        check_bundle_layout(self.install_root, manifest)
        dependencies = check_host_dependencies(spec.preferred_cli)
        if not dependencies.available:
            raise ShogunDistributionError(dependencies.detail)
        policy = spec.team_policy
        workers = int(policy.get("max_active_workers", 2))
        channel = None
        try:
            if spec.credential_refs:
                if self.credential_broker is None:
                    raise ValueError("Shogun credential references require a CredentialBroker")
                channel = self.credential_injector.prepare(
                    spec.credential_refs, broker=self.credential_broker, run_dir=spec.config_dir,
                )
            worker_worktrees: dict[str, Path] = {}
            if spec.execution_mode == "team" and spec.base_commit:
                repository_root = spec.repository_root or spec.workspace
                workers_spec = [
                    WorkerSpec(
                        worker_id=f"ashigaru{index}",
                        work_package_id=str(package.get("id", f"wp-{index}")),
                        allowed_paths=tuple(package.get("allowedPaths", [])),
                    )
                    for index, package in enumerate(spec.work_packages, start=1)
                ]
                if workers_spec:
                    worktree_registry = WorktreeManager().create(
                        repository_root=repository_root,
                        base_commit=spec.base_commit,
                        team_id=spec.config_dir.name,
                        workers=workers_spec,
                        state_root=self.state_root,
                    )
                    worktree_registry.write(spec.config_dir / "worktree-registry.json")
                    worker_worktrees = {
                        worker.worker_id: worker.worktree for worker in worktree_registry.workers
                    }
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
                worker_worktrees=worker_worktrees,
            )
            if channel is not None:
                environment = dict(generated.environment)
                environment["PATH"] = os.pathsep.join((
                    str(channel.launcher_dir), os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                ))
                environment["SKILLIFY_SHOGUN_CREDENTIAL_SOCKET"] = str(channel.socket_path)
                generated = replace(generated, environment=environment)
            team = self.lifecycle.start(spec.config_dir.name, generated, install_root=self.install_root)
        except Exception:
            if channel is not None:
                self.credential_injector.destroy(channel)
            raise
        handle_id = uuid.uuid4().hex
        handle = ProviderHandle(
            handle_id, "shogun", SHOGUN_VERSION, generated.queue_dir.as_uri(), 0,
        )
        try:
            team.handle.write(team.run_dir / "team-handle.json")
        except Exception:
            if channel is not None:
                self.credential_injector.destroy(channel)
            self.lifecycle.stop(team)
            raise
        self._handles[handle_id] = _RuntimeState(spec, generated, team, channel)
        return handle

    def create_session(self, handle: ProviderHandle, spec: TaskSpec) -> ProviderSession:
        runtime = self._handles.get(handle.handle_id)
        if runtime is None:
            raise ValueError("Shogun handle is not active")
        session = ProviderSession(spec.task_id, uuid.uuid4().hex, handle.handle_id)
        command = {
            "id": spec.task_id,
            "from": "skillify",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "task_assigned",
            "content": spec.prompt,
            "read": False,
            "work_packages": list(runtime.spec.work_packages),
        }
        try:
            _atomic_yaml(
                runtime.generated.queue_dir / "inbox" / "shogun.yaml",
                {"messages": [command]},
            )
            state_path = runtime.team.run_dir / "provider-state.json"
            temporary = state_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps({
                "handle_id": handle.handle_id,
                "task_id": session.task_id,
                "session_id": session.session_id,
            }, sort_keys=True), encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, state_path)
        except Exception:
            self._handles.pop(handle.handle_id, None)
            if runtime.credential_channel is not None:
                self.credential_injector.destroy(runtime.credential_channel)
            self.lifecycle.stop(runtime.team)
            raise
        self._sessions[session.session_id] = session
        return session

    def recover(self, task_id: str) -> ProviderRecovery:
        run_dir = (self.cache_root / task_id).resolve()
        handle_path = run_dir / "team-handle.json"
        state_path = run_dir / "provider-state.json"
        if not handle_path.exists():
            guard_matches = False
            try:
                guard_matches = self.lifecycle.guard_path.read_text(encoding="utf-8") == task_id
            except FileNotFoundError:
                pass
            if run_dir.exists() or guard_matches:
                shutil.rmtree(run_dir, ignore_errors=True)
                if guard_matches:
                    self.lifecycle.guard_path.unlink(missing_ok=True)
                return ProviderRecovery("dead")
            return ProviderRecovery("absent")
        try:
            team_handle = TeamHandle.read(handle_path)
            if team_handle.run_dir.resolve() != run_dir:
                raise ValueError("persisted Shogun run directory does not match task")
        except (OSError, ValueError, json.JSONDecodeError):
            shutil.rmtree(run_dir, ignore_errors=True)
            self.lifecycle.guard_path.unlink(missing_ok=True)
            return ProviderRecovery("dead")
        team = ActiveTeam(
            task_id, team_handle, run_dir, run_dir / "queue", self.lifecycle.guard_path,
        )
        # Reconcile git-worktree/merge state (only present for teams using the
        # git-worktree feature; a no-op for everyone else). A "corrupt"
        # diagnosis is the one case that overrides the tmux-liveness-based
        # status decision below -- it always forces "dead", the safest of the
        # three existing statuses, regardless of whether tmux is still alive.
        worktree_diagnosis = _diagnose_worktree_state(run_dir)
        if worktree_diagnosis is not None and worktree_diagnosis.status == "corrupt":
            self.runtime.terminate(team_handle)
            self.runtime.cleanup_processes(team_handle)
            # Deliberately not self.lifecycle._release(team): that helper
            # rmtree's run_dir, which would destroy the very
            # recovery-state.json (and the registry/worktrees it describes)
            # this diagnosis exists to preserve for forensics. Release only
            # the active-team guard so the endpoint isn't stuck thinking a
            # team is still active; leave run_dir on disk for inspection.
            team.guard_path.unlink(missing_ok=True)
            if self.lifecycle.active == team:
                self.lifecycle.active = None
            return ProviderRecovery("dead")
        if not self.runtime.is_alive(team_handle):
            self.runtime.terminate(team_handle)
            self.runtime.cleanup_processes(team_handle)
            self.lifecycle._release(team)
            return ProviderRecovery("dead")
        try:
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            if set(persisted) != {"handle_id", "task_id", "session_id"}:
                raise ValueError("persisted Shogun provider state has unexpected fields")
            if persisted["task_id"] != task_id or any(
                not isinstance(persisted[name], str) or not persisted[name]
                for name in ("handle_id", "task_id", "session_id")
            ):
                raise ValueError("persisted Shogun provider state is invalid")
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            self.runtime.terminate(team_handle)
            self.runtime.cleanup_processes(team_handle)
            self.lifecycle._release(team)
            return ProviderRecovery("dead")
        channel = None
        settings_path = run_dir / "config" / "settings.yaml"
        try:
            settings = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
            refs = settings.get("skillify", {}).get("credential_refs", {})
            if refs:
                if self.credential_broker is None or not isinstance(refs, dict):
                    raise ValueError("recovering credentialed team requires its CredentialBroker")
                channel = self.credential_injector.prepare(
                    refs, broker=self.credential_broker, run_dir=run_dir,
                )
        except Exception:
            self.runtime.terminate(team_handle)
            self.runtime.cleanup_processes(team_handle)
            self.lifecycle._release(team)
            return ProviderRecovery("dead")
        generated = GeneratedShogunConfig(
            settings_path, run_dir / "config" / "opencode-permissions.yaml",
            run_dir / "queue", (str(run_dir / "shutsujin_departure.sh"),), {},
        )
        handle = ProviderHandle(
            persisted["handle_id"], "shogun", SHOGUN_VERSION, generated.queue_dir.as_uri(), 0,
        )
        session = ProviderSession(task_id, persisted["session_id"], handle.handle_id)
        self.lifecycle.active = team
        self._handles[handle.handle_id] = _RuntimeState(None, generated, team, channel)
        self._sessions[session.session_id] = session
        return ProviderRecovery("live", handle, session)

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
        expected_packages = {
            str(package.get("packageId") or package.get("id"))
            for package in (runtime.spec.work_packages if runtime.spec is not None else ())
            if package.get("packageId") or package.get("id")
        }
        require_review = bool(
            runtime.spec is not None
            and runtime.spec.team_policy.get("require_independent_review", True)
        )
        duration_minutes = int(
            runtime.spec.team_policy.get("max_team_duration_minutes", 120)
            if runtime.spec is not None else 120
        )
        deadline = self.monotonic() + duration_minutes * 60
        completed_packages: set[str] = set()
        review_completed = False
        for _ in self.runtime.queue_states(runtime.generated.queue_dir, runtime.team.handle):
            terminal = False
            for item in scan_queue(runtime.generated.queue_dir):
                events = mapper.map_all(
                    task_id=session.task_id, session_id=session.session_id,
                    item=item, occurred_at=datetime.now(timezone.utc),
                )
                for event in events:
                    yield event
                    sequence = max(sequence, int(event.details.get("sequence", 0)))
                    if event.type is EventType.WORK_PACKAGE_COMPLETED:
                        package_id = event.details.get("work_package_id")
                        if package_id:
                            completed_packages.add(str(package_id))
                    elif event.type is EventType.REVIEW_COMPLETED:
                        review_completed = True
                    terminal = terminal or event.type in {
                        EventType.TEAM_COMPLETED, EventType.TEAM_FAILED, EventType.TEAM_CANCELLED,
                    }
            if terminal:
                return
            if expected_packages and expected_packages <= completed_packages and (
                review_completed or not require_review
            ):
                sequence += 1
                yield TaskEvent(
                    session.task_id, session.session_id, "shogun", SHOGUN_VERSION,
                    TASK_PROTOCOL_VERSION, PROVIDER_CONTRACT_VERSION,
                    datetime.now(timezone.utc), EventType.TEAM_COMPLETED, TaskState.SUCCEEDED,
                    {"sequence": sequence, "stage": "skillify-derived-terminal"},
                )
                return
            if self.monotonic() >= deadline:
                sequence += 1
                yield TaskEvent(
                    session.task_id, session.session_id, "shogun", SHOGUN_VERSION,
                    TASK_PROTOCOL_VERSION, PROVIDER_CONTRACT_VERSION,
                    datetime.now(timezone.utc), EventType.TEAM_FAILED, TaskState.FAILED,
                    {
                        "sequence": sequence, "stage": "skillify-timeout",
                        "reason_code": "team-duration-exceeded",
                    },
                )
                return
        sequence += 1
        yield TaskEvent(
            session.task_id, session.session_id, "shogun", SHOGUN_VERSION,
            TASK_PROTOCOL_VERSION, PROVIDER_CONTRACT_VERSION,
            datetime.now(timezone.utc), EventType.TEAM_FAILED, TaskState.FAILED,
            {
                "sequence": sequence, "stage": "skillify-runtime-ended",
                "reason_code": "team-ended-without-terminal",
            },
        )

    def cancel(self, handle: ProviderHandle, session: ProviderSession) -> ProviderResult:
        runtime = self._handles.pop(handle.handle_id, None)
        self._sessions.pop(session.session_id, None)
        if runtime is not None:
            if runtime.credential_channel is not None:
                self.credential_injector.destroy(runtime.credential_channel)
            self.lifecycle.cancel(runtime.team)
        return ProviderResult(TaskState.CANCELLED)

    def stop(self, handle: ProviderHandle) -> ProviderResult:
        runtime = self._handles.pop(handle.handle_id, None)
        if runtime is not None:
            if runtime.credential_channel is not None:
                self.credential_injector.destroy(runtime.credential_channel)
            self.lifecycle.stop(runtime.team)
        for session_id, session in tuple(self._sessions.items()):
            if session.handle_id == handle.handle_id:
                self._sessions.pop(session_id, None)
        return ProviderResult(TaskState.SUCCEEDED)
