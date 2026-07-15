from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

import typer
import yaml

from skillify.agent.events import EventType, TaskState
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec, TaskSpec
from skillify.agent.providers.opencode import (
    LifecycleReasonCode,
    OpenCodeError,
    OpenCodeProvider,
    ProviderCleanupPending,
    ProviderCrashed,
    ProviderTimeout,
    linux_process_group_members,
)
from skillify.common.config import (
    AgentLocalConfig,
    AgentPaths,
    load_agent_local_config,
    load_agent_paths,
    save_agent_local_config,
)
from skillify.install.opencode_distribution import (
    check_opencode_distribution,
    detect_opencode_platform,
    opencode_version,
    resolve_distribution_paths,
)

agent_app = typer.Typer(
    name="agent",
    help="Manage the local Skillify endpoint agent.",
    no_args_is_help=True,
    rich_markup_mode=None,
)


class AgentErrorCode(str, Enum):
    OK = "OK"
    CONFIG_INVALID = "AGENT_CONFIG_INVALID"
    WORKSPACE_UNAUTHORIZED = "AGENT_WORKSPACE_UNAUTHORIZED"
    PROVIDER_UNAVAILABLE = "AGENT_PROVIDER_UNAVAILABLE"
    PROVIDER_FAILED = "AGENT_PROVIDER_FAILED"
    TASK_FAILED = "AGENT_TASK_FAILED"


class AgentExit(IntEnum):
    OK = 0
    CONFIG_INVALID = 10
    WORKSPACE_UNAUTHORIZED = 11
    PROVIDER_UNAVAILABLE = 12
    PROVIDER_FAILED = 13
    TASK_FAILED = 14


_EXIT_BY_CODE = {
    AgentErrorCode.OK: AgentExit.OK,
    AgentErrorCode.CONFIG_INVALID: AgentExit.CONFIG_INVALID,
    AgentErrorCode.WORKSPACE_UNAUTHORIZED: AgentExit.WORKSPACE_UNAUTHORIZED,
    AgentErrorCode.PROVIDER_UNAVAILABLE: AgentExit.PROVIDER_UNAVAILABLE,
    AgentErrorCode.PROVIDER_FAILED: AgentExit.PROVIDER_FAILED,
    AgentErrorCode.TASK_FAILED: AgentExit.TASK_FAILED,
}


class AgentCommandFailure(Exception):
    def __init__(self, code: AgentErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentRuntimeState:
    schema_version: int
    owner_uid: int
    pid: int
    pgid: int
    process_session_id: int
    process_start_token: str
    executable: str
    workspace_hash: str
    task_id: str
    session_id: str
    provider_version: str
    started_at: str
    state: str


def write_runtime_state(paths: AgentPaths, state: AgentRuntimeState) -> None:
    paths.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = paths.runtime_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(asdict(state), sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, paths.runtime_path)


def read_runtime_state(paths: AgentPaths) -> AgentRuntimeState | None:
    try:
        try:
            runtime_text = paths.runtime_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        data = json.loads(runtime_text)
        if not isinstance(data, dict): raise ValueError("runtime state must be an object")
        state = AgentRuntimeState(**data)
        integer_fields = (
            state.schema_version, state.owner_uid, state.pid, state.pgid,
            state.process_session_id,
        )
        string_fields = (
            state.process_start_token, state.executable, state.workspace_hash, state.task_id,
            state.provider_version, state.started_at, state.state,
        )
        if any(type(value) is not int for value in integer_fields):
            raise ValueError("runtime integer fields are invalid")
        if any(not isinstance(value, str) or not value for value in string_fields):
            raise ValueError("runtime string fields are invalid")
        if (state.schema_version != 1 or state.pid <= 0 or state.pgid <= 0 or
                state.process_session_id <= 0):
            raise ValueError("runtime identity fields are invalid")
        sessionless_states = {"starting", "cleanup_pending"}
        if ((state.state in sessionless_states and state.session_id != "") or
                (state.state not in sessionless_states and not state.session_id)):
            raise ValueError("runtime session fields are invalid")
        return state
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "runtime state is invalid") from exc


def validate_owned_process(state: AgentRuntimeState, inspector) -> bool:
    return (state.schema_version == 1 and state.owner_uid == os.getuid() and
            inspector.is_alive(state.pid) and inspector.pgid(state.pid) == state.pgid and
            inspector.session_id(state.pid) == state.process_session_id and
            inspector.start_token(state.pid) == state.process_start_token and
            inspector.uid(state.pid) == state.owner_uid and
            inspector.executable(state.pid) == state.executable)


def _owned_group_snapshot(state: AgentRuntimeState, inspector):
    leader_alive = inspector.is_alive(state.pid)
    if leader_alive and not validate_owned_process(state, inspector):
        return None
    try:
        leader_start = int(state.process_start_token)
        members = tuple(inspector.group_members(state.pgid))
    except (OSError, TypeError, ValueError):
        return None
    if not members:
        return None if leader_alive else ()
    leader_seen = False
    for member in members:
        try:
            if (member.pgid != state.pgid or member.sid != state.process_session_id or
                    member.uid != state.owner_uid or int(member.start_token) < leader_start):
                return None
            if member.pid == state.pid:
                leader_seen = True
                if member.start_token != state.process_start_token:
                    return None
        except (AttributeError, TypeError, ValueError):
            return None
    if leader_alive and not leader_seen:
        return None
    return members


def _confirmed_owned_group(state: AgentRuntimeState, inspector):
    first = _owned_group_snapshot(state, inspector)
    if first is None or not first:
        return first
    return _owned_group_snapshot(state, inspector)


def stop_owned_process(paths: AgentPaths, inspector, killpg=os.killpg) -> bool:
    state = read_runtime_state(paths)
    if state is None: return True
    members = _confirmed_owned_group(state, inspector)
    if members is None:
        return False
    if not members:
        paths.runtime_path.unlink(missing_ok=True)
        return True
    try:
        killpg(state.pgid, signal.SIGTERM)
    except ProcessLookupError:
        members = _confirmed_owned_group(state, inspector)
        if members == ():
            paths.runtime_path.unlink(missing_ok=True)
            return True
        return False
    if not inspector.wait_group_exited(state.pgid, 5.0):
        members = _confirmed_owned_group(state, inspector)
        if members is None:
            return False
        if not members:
            paths.runtime_path.unlink(missing_ok=True)
            return True
        try:
            killpg(state.pgid, signal.SIGKILL)
        except ProcessLookupError:
            members = _confirmed_owned_group(state, inspector)
            if members == ():
                paths.runtime_path.unlink(missing_ok=True)
                return True
            return False
        if not inspector.wait_group_exited(state.pgid, 1.0):
            return False
    paths.runtime_path.unlink(missing_ok=True)
    return True


def append_agent_log(paths: AgentPaths, event: str, **fields: str) -> None:
    allowed = {key: value for key, value in fields.items() if key in {
        "task_id", "session_id", "provider_version", "state"
    }}
    reason = fields.get("reason_code")
    try:
        if reason:
            allowed["reason_code"] = LifecycleReasonCode(reason).value
    except ValueError:
        pass
    try:
        paths.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with paths.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, **allowed}, sort_keys=True) + "\n")
        paths.log_path.chmod(0o600)
    except OSError:
        return


class LinuxProcessInspector:
    def is_alive(self, pid: int) -> bool:
        return Path(f"/proc/{pid}").is_dir()
    def pgid(self, pid: int) -> int:
        return os.getpgid(pid)
    def start_token(self, pid: int) -> str:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]
    def uid(self, pid: int) -> int:
        return Path(f"/proc/{pid}").stat().st_uid
    def session_id(self, pid: int) -> int:
        return os.getsid(pid)
    def executable(self, pid: int) -> str:
        return str(Path(os.readlink(f"/proc/{pid}/exe")).resolve(strict=True))
    def group_members(self, pgid: int):
        return linux_process_group_members(pgid)
    def wait_group_exited(self, pgid: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while self.group_members(pgid) and time.monotonic() < deadline:
            time.sleep(0.05)
        return not self.group_members(pgid)
    def wait_exited(self, pid: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while self.is_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        return not self.is_alive(pid)


def _emit(*, ok: bool, code: AgentErrorCode, message: str, data: dict[str, Any], output: str) -> None:
    payload = {"ok": ok, "code": code.value, "message": message, "data": data}
    if output == "json":
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(message)


def _fail(error: AgentCommandFailure, output: str) -> None:
    _emit(ok=False, code=error.code, message=error.message, data={}, output=output)
    raise typer.Exit(int(_EXIT_BY_CODE[error.code]))


def _config():
    paths = load_agent_paths()
    try:
        return paths, load_agent_local_config(paths)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "agent config is invalid") from exc


def _workspace(value: Path, config: AgentLocalConfig) -> Path:
    try:
        resolved = value.resolve(strict=True)
    except OSError as exc:
        raise AgentCommandFailure(AgentErrorCode.WORKSPACE_UNAUTHORIZED, "workspace is not registered") from exc
    if str(resolved) not in config.allowed_workspaces:
        raise AgentCommandFailure(AgentErrorCode.WORKSPACE_UNAUTHORIZED, "workspace is not registered")
    return resolved


def _read_prompt(path: str) -> str:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "prompt file is unavailable") from exc
    if not text.strip():
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "prompt file is empty")
    return text


def _resolve_task(task: str | None, prompt_file: str | None) -> str:
    if (task is None) == (prompt_file is None):
        raise AgentCommandFailure(
            AgentErrorCode.CONFIG_INVALID,
            "exactly one of --task and --prompt-file is required",
        )
    if prompt_file is not None:
        return _read_prompt(prompt_file)
    assert task is not None
    if task == "-":
        return _read_prompt("-")
    candidate = Path(task)
    try:
        if candidate.is_file():
            return _read_prompt(task)
        if candidate.exists():
            raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "task path is not a file")
    except OSError as exc:
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "task is unavailable") from exc
    if not task.strip():
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "task is empty")
    return task


def _build_provider() -> OpenCodeProvider:
    return OpenCodeProvider()


def _runtime_config(config: AgentLocalConfig) -> ModelRuntimeConfig:
    if not all((config.model_endpoint, config.model_provider, config.model_name,
                config.allowed_model_hosts, config.credential_env_names)):
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "model runtime config is incomplete")
    try:
        return ModelRuntimeConfig(
            provider=config.model_provider,
            endpoint=config.model_endpoint,
            model=config.model_name,
            allowed_endpoint_hosts=config.allowed_model_hosts,
            credential_env_names=config.credential_env_names,
        )
    except ValueError as exc:
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "model runtime config is invalid") from exc


class _TerminationRequested(Exception):
    pass


def _raise_termination(signum, frame) -> None:
    raise _TerminationRequested()


def _run_local_task(workspace: Path, prompt: str, paths: AgentPaths,
                    config: AgentLocalConfig) -> str:
    provider = _build_provider(); handle = None; session = None
    terminal = "failed"; task_id = uuid.uuid4().hex
    previous_sigterm = None; sigterm_installed = False; stop_error = None
    cleanup_handed_off = False
    try:
        runtime = _runtime_config(config)
    except AgentCommandFailure:
        runtime_fields = (
            config.model_endpoint, config.model_provider, config.model_name,
            config.allowed_model_hosts, config.credential_env_names,
        )
        if not all(runtime_fields) and not provider.probe().available:
            raise AgentCommandFailure(AgentErrorCode.PROVIDER_UNAVAILABLE, "opencode is not installed")
        raise
    config_dir = paths.cache_dir / "opencode" / hashlib.sha256(str(workspace).encode()).hexdigest()
    start_spec = ProviderStartSpec(
        workspace=workspace, allowed_paths=(workspace,), config_dir=config_dir,
        runtime=runtime,
        source_config_path=(
            Path(config.opencode_user_config_path)
            if config.opencode_user_config_path is not None else None
        ),
    )
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _raise_termination)
    sigterm_installed = True
    try:
        append_agent_log(paths, "run.start", task_id=task_id, state="starting")
        handle = provider.start(start_spec)
        owned = provider.ownership(handle)
        runtime_state = AgentRuntimeState(
            schema_version=1, owner_uid=owned["uid"], pid=owned["pid"], pgid=owned["pgid"],
            process_session_id=owned["sid"],
            process_start_token=owned["start_token"], executable=owned["executable"],
            workspace_hash=hashlib.sha256(str(workspace).encode()).hexdigest(),
            task_id=task_id, session_id="", provider_version=handle.provider_version,
            started_at=datetime.now(timezone.utc).isoformat(), state="starting",
        )
        write_runtime_state(paths, runtime_state)
        session = provider.create_session(handle, TaskSpec(task_id=task_id, prompt=prompt))
        write_runtime_state(paths, replace(
            runtime_state, session_id=session.session_id, state="running",
        ))
        for event in provider.stream_events(handle, session):
            reason = event.details.get("reason_code")
            append_agent_log(paths, "provider.event", task_id=event.task_id,
                             session_id=event.session_id, provider_version=event.provider_version,
                             state=event.state.value, reason_code=str(reason) if reason else "")
            if event.type is EventType.TASK_FINISHED: terminal = event.state.value
            elif event.type is EventType.TASK_BLOCKED: terminal = "blocked"
        return terminal
    except ProviderCleanupPending as exc:
        if sigterm_installed:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        handle = exc.handle
        owned = provider.ownership(handle)
        try:
            write_runtime_state(paths, AgentRuntimeState(
                schema_version=1, owner_uid=owned["uid"], pid=owned["pid"], pgid=owned["pgid"],
                process_session_id=owned["sid"], process_start_token=owned["start_token"],
                executable=owned["executable"],
                workspace_hash=hashlib.sha256(str(workspace).encode()).hexdigest(),
                task_id=task_id, session_id="", provider_version=handle.provider_version,
                started_at=datetime.now(timezone.utc).isoformat(), state="cleanup_pending",
            ))
        except OSError as write_error:
            raise AgentCommandFailure(
                AgentErrorCode.PROVIDER_FAILED, "provider recovery state could not be persisted",
            ) from write_error
        cleanup_handed_off = True
        terminal = "cleanup_pending"
        append_agent_log(
            paths, "start.cleanup_pending", task_id=task_id, state=terminal,
            reason_code=LifecycleReasonCode.STOP_UNCONFIRMED.value,
        )
        raise AgentCommandFailure(
            AgentErrorCode.PROVIDER_FAILED, "provider cleanup is pending",
        ) from exc
    except (KeyboardInterrupt, _TerminationRequested):
        terminal = "cancelled"; return terminal
    except Exception as exc:
        append_agent_log(paths, "run.error", task_id=task_id, state="failed",
                         reason_code=LifecycleReasonCode.PROVIDER_FAILED.value)
        raise AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider execution failed") from exc
    finally:
        try:
            if sigterm_installed:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            if not cleanup_handed_off and handle is not None and session is not None:
                try: provider.cancel(handle, session)
                except Exception: append_agent_log(
                    paths, "abort.error", task_id=task_id, state=terminal,
                    reason_code=LifecycleReasonCode.ABORT_FAILED.value,
                )
            if not cleanup_handed_off and handle is not None:
                try:
                    provider.stop(handle)
                except Exception as exc:
                    stop_error = exc
                    append_agent_log(
                        paths, "stop.error", task_id=task_id, state=terminal,
                        reason_code=LifecycleReasonCode.STOP_UNCONFIRMED.value,
                    )
            if not cleanup_handed_off and (handle is None or stop_error is None):
                paths.runtime_path.unlink(missing_ok=True)
            append_agent_log(paths, "run.stop", task_id=task_id, state=terminal)
            if stop_error is not None:
                raise AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider stop was not confirmed") from stop_error
        finally:
            if sigterm_installed:
                signal.signal(signal.SIGTERM, previous_sigterm)


@agent_app.command()
def doctor(output: str = typer.Option("text", "--format")) -> None:
    """Check local endpoint-agent prerequisites."""
    try:
        paths, config = _config()
        try:
            distribution_paths = resolve_distribution_paths(
                config.opencode_manifest_path, config.opencode_artifact_root,
            )
        except ValueError as exc:
            raise AgentCommandFailure(
                AgentErrorCode.CONFIG_INVALID, "OpenCode distribution config is invalid",
            ) from exc
        executable = shutil.which("opencode")
        checks: list[dict[str, object]] = []
        try:
            os_name, arch, libc, cpu = detect_opencode_platform()
        except (OSError, TypeError, ValueError):
            platform_ok = False
            platform_detail = "unsupported platform"
        else:
            platform_ok = True
            platform_detail = f"{os_name}/{arch}/{libc}/{cpu}"
        checks.append({"name": "platform", "ok": platform_ok, "detail": platform_detail})
        opencode_ok = False
        opencode_detail = "not installed"
        if executable is not None:
            try:
                actual_version = opencode_version([executable, "--version"]).strip()
            except (OSError, subprocess.SubprocessError, ValueError):
                opencode_detail = "version probe failed"
            else:
                opencode_ok = actual_version == "1.15.11"
                opencode_detail = actual_version if opencode_ok else "unsupported version"
        checks.append({"name": "opencode", "ok": opencode_ok, "detail": opencode_detail})
        git_path = shutil.which("git")
        checks.append({"name": "git", "ok": git_path is not None,
                       "detail": git_path or "not installed"})
        try:
            _runtime_config(config)
        except AgentCommandFailure:
            model_ok = False
            model_detail = "not configured or invalid"
        else:
            model_ok = True
            model_detail = "configured; reachability requires test-env"
        checks.append({"name": "model-endpoint", "ok": model_ok, "detail": model_detail})
        cache_ok = paths.cache_dir.is_dir() and os.access(paths.cache_dir, os.R_OK | os.W_OK)
        checks.append({"name": "skill-cache", "ok": cache_ok,
                       "detail": str(paths.cache_dir) if cache_ok else "not initialized or inaccessible"})
        checks.append({"name": "mcp", "ok": False, "detail": "not configured; runtime check requires test-env"})
        workspaces = [Path(value) for value in config.allowed_workspaces]
        workspace_ok = bool(workspaces) and all(
            value.is_dir() and os.access(value, os.R_OK | os.W_OK) for value in workspaces
        )
        checks.append({"name": "workspace", "ok": workspace_ok,
                       "detail": "configured and writable" if workspace_ok else "not configured or inaccessible"})
        data: dict[str, Any] = {"opencode": executable, "checks": checks}
        if distribution_paths is not None:
            manifest_path, artifact_root = distribution_paths
            checks = check_opencode_distribution(
                manifest_path=manifest_path,
                artifact_root=artifact_root,
                platform_detector=detect_opencode_platform,
                version_runner=opencode_version,
            )
            data["distribution"] = [asdict(check) for check in checks]
            if not all(check.ok for check in checks):
                _emit(
                    ok=False,
                    code=AgentErrorCode.PROVIDER_UNAVAILABLE,
                    message="offline OpenCode distribution check failed",
                    data=data,
                    output=output,
                )
                raise typer.Exit(int(AgentExit.PROVIDER_UNAVAILABLE))
        # Model, cache, MCP, and workspace readiness are reported truthfully but
        # are deployment-specific admission gates rather than binary prerequisites.
        required_ok = platform_ok and opencode_ok and git_path is not None
        _emit(ok=required_ok, code=(AgentErrorCode.OK if required_ok else AgentErrorCode.PROVIDER_UNAVAILABLE),
              message=("local prerequisites available" if required_ok else "local prerequisites unavailable"),
              data=data, output=output)
        if not required_ok:
            raise typer.Exit(int(AgentExit.PROVIDER_UNAVAILABLE))
    except AgentCommandFailure as exc:
        _fail(exc, output)


@agent_app.command()
def init(
    workspace: Path = typer.Option(..., "--workspace"),
    provider: str = typer.Option("opencode", "--provider"),
    model_endpoint: str | None = typer.Option(None, "--model-endpoint"),
    model_provider: str | None = typer.Option(None, "--model-provider"),
    model_name: str | None = typer.Option(None, "--model"),
    allowed_model_host: list[str] = typer.Option([], "--allowed-model-host"),
    credential_env: list[str] = typer.Option([], "--credential-env"),
    output: str = typer.Option("text", "--format"),
) -> None:
    """Register an explicit workspace."""
    try:
        if provider != "opencode":
            raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "provider must be opencode")
        try:
            resolved = workspace.resolve(strict=True)
        except OSError as exc:
            raise AgentCommandFailure(
                AgentErrorCode.WORKSPACE_UNAUTHORIZED,
                "workspace is not allowed",
            ) from exc
        if not resolved.is_dir() or resolved in {Path("/"), Path.home().resolve()}:
            raise AgentCommandFailure(AgentErrorCode.WORKSPACE_UNAUTHORIZED, "workspace is not allowed")
        paths, config = _config()
        allowed = tuple(sorted(set(config.allowed_workspaces) | {str(resolved)}))
        updated = replace(
            config,
            provider="opencode",
            allowed_workspaces=allowed,
            model_endpoint=model_endpoint or config.model_endpoint,
            model_provider=model_provider or config.model_provider,
            model_name=model_name or config.model_name,
            allowed_model_hosts=tuple(allowed_model_host) or config.allowed_model_hosts,
            credential_env_names=tuple(credential_env) or config.credential_env_names,
        )
        try:
            save_agent_local_config(paths, updated)
        except OSError as exc:
            raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "agent config is invalid") from exc
        _emit(
            ok=True,
            code=AgentErrorCode.OK,
            message="workspace registered",
            data={"workspace": str(resolved)},
            output=output,
        )
    except AgentCommandFailure as exc:
        _fail(exc, output)


@agent_app.command()
def run(
    workspace: Path = typer.Option(..., "--workspace"),
    task: str | None = typer.Option(None, "--task"),
    prompt_file: str | None = typer.Option(None, "--prompt-file", hidden=True),
    output: str = typer.Option("text", "--format"),
) -> None:
    """Run an endpoint-agent task locally."""
    try:
        paths, config = _config()
        resolved = _workspace(workspace, config)
        result = _run_local_task(resolved, _resolve_task(task, prompt_file), paths, config)
        if result != "succeeded":
            raise AgentCommandFailure(AgentErrorCode.TASK_FAILED, "task failed")
        _emit(
            ok=True,
            code=AgentErrorCode.OK,
            message="task succeeded",
            data={"state": result},
            output=output,
        )
    except AgentCommandFailure as exc:
        _fail(exc, output)


@agent_app.command()
def status(output: str = typer.Option("text", "--format")) -> None:
    """Show local endpoint-agent state."""
    try:
        paths, _ = _config(); state = read_runtime_state(paths)
        if state is None:
            data = {"state": "stopped"}
        else:
            members = _confirmed_owned_group(state, LinuxProcessInspector())
            if members == ():
                paths.runtime_path.unlink(missing_ok=True); data = {"state": "stopped"}
            else:
                leader_present = bool(members) and any(
                    member.pid == state.pid for member in members
                )
                visible_state = state.state if leader_present else "degraded"
                data = {"state": visible_state, "task_id": state.task_id}
                if state.session_id:
                    data["session_id"] = state.session_id
        _emit(ok=True, code=AgentErrorCode.OK, message=str(data["state"]), data=data, output=output)
    except AgentCommandFailure as exc:
        _fail(exc, output)
    except OSError:
        _fail(AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "runtime state is invalid"), output)


@agent_app.command()
def stop(output: str = typer.Option("text", "--format")) -> None:
    """Stop the owned local provider process."""
    try:
        paths = load_agent_paths()
        if not stop_owned_process(paths, LinuxProcessInspector()):
            raise AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider stop was not confirmed")
        _emit(ok=True, code=AgentErrorCode.OK, message="stopped", data={"state": "stopped"}, output=output)
    except AgentCommandFailure as exc:
        _fail(exc, output)
    except OSError:
        _fail(AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "runtime state is invalid"), output)


@agent_app.command()
def logs(
    task_id: str | None = typer.Option(None, "--task-id"),
    lines: int = typer.Option(100, "--lines", min=1, max=10000),
    output: str = typer.Option("text", "--format"),
) -> None:
    """Read redacted local lifecycle logs."""
    path = load_agent_paths().log_path
    try:
        log_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = []
    except OSError:
        _fail(AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "agent logs are invalid"), output)
    else:
        safe_events = {
            "run.start", "provider.event", "run.error", "abort.error", "stop.error",
            "run.stop", "start.cleanup_pending",
        }
        safe_states = {
            "queued", "awaiting_approval", "starting", "running", "blocked",
            "succeeded", "failed", "cancelled", "cleanup_pending",
        }
        task_pattern = re.compile(r"^[0-9a-f]{32}$")
        session_pattern = re.compile(r"^(?:session-[0-9]{1,16}|ses_[A-Za-z0-9]{8,64})$")
        version_pattern = re.compile(r"^(?:1\.15\.11|unknown)$")
        parsed = []
        for line in log_text.splitlines():
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(record, dict) or record.get("event") not in safe_events:
                continue
            if not isinstance(record.get("task_id"), str) or not task_pattern.fullmatch(record["task_id"]):
                continue
            if record.get("state") not in safe_states:
                continue
            if "session_id" in record and (
                not isinstance(record["session_id"], str) or
                not session_pattern.fullmatch(record["session_id"])
            ):
                continue
            if "provider_version" in record and (
                not isinstance(record["provider_version"], str) or
                not version_pattern.fullmatch(record["provider_version"])
            ):
                continue
            if "reason_code" in record:
                try:
                    LifecycleReasonCode(record["reason_code"])
                except (TypeError, ValueError):
                    continue
            if record["event"] == "provider.event" and not all(
                key in record for key in ("session_id", "provider_version")
            ):
                continue
            if task_id is not None and record.get("task_id") != task_id:
                continue
            safe = {
                key: value for key, value in record.items()
                if key in {"event", "task_id", "session_id", "provider_version", "state", "reason_code"}
                and isinstance(value, str)
            }
            if safe.get("event") and (task_id is None or safe.get("task_id") == task_id):
                parsed.append(safe)
        content = parsed[-lines:]
    _emit(ok=True, code=AgentErrorCode.OK, message="logs", data={"lines": content}, output=output)
