from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
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
from skillify.agent.providers.opencode import OpenCodeError, OpenCodeProvider, ProviderCrashed, ProviderTimeout
from skillify.common.config import (
    AgentLocalConfig,
    AgentPaths,
    load_agent_local_config,
    load_agent_paths,
    save_agent_local_config,
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
        integer_fields = (state.schema_version, state.owner_uid, state.pid, state.pgid)
        string_fields = (
            state.process_start_token, state.executable, state.workspace_hash, state.task_id,
            state.session_id, state.provider_version, state.started_at, state.state,
        )
        if any(type(value) is not int for value in integer_fields):
            raise ValueError("runtime integer fields are invalid")
        if any(not isinstance(value, str) or not value for value in string_fields):
            raise ValueError("runtime string fields are invalid")
        if state.schema_version != 1 or state.pid <= 0 or state.pgid <= 0:
            raise ValueError("runtime identity fields are invalid")
        return state
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "runtime state is invalid") from exc


def validate_owned_process(state: AgentRuntimeState, inspector) -> bool:
    return (state.schema_version == 1 and state.owner_uid == os.getuid() and
            inspector.is_alive(state.pid) and inspector.pgid(state.pid) == state.pgid and
            inspector.start_token(state.pid) == state.process_start_token and
            Path(inspector.executable(state.pid)).name == Path(state.executable).name)


def stop_owned_process(paths: AgentPaths, inspector, killpg=os.killpg) -> bool:
    state = read_runtime_state(paths)
    if state is None: return True
    if not validate_owned_process(state, inspector):
        paths.runtime_path.unlink(missing_ok=True)
        return False
    # Revalidate immediately before signaling to close the PID-reuse window.
    if not validate_owned_process(state, inspector):
        paths.runtime_path.unlink(missing_ok=True)
        return False
    killpg(state.pgid, signal.SIGTERM)
    if not inspector.wait_exited(state.pid, 5.0):
        killpg(state.pgid, signal.SIGKILL)
        if not inspector.wait_exited(state.pid, 1.0):
            return False
    paths.runtime_path.unlink(missing_ok=True)
    return True


def append_agent_log(paths: AgentPaths, event: str, **fields: str) -> None:
    allowed = {key: value for key, value in fields.items() if key in {
        "task_id", "session_id", "provider_version", "state", "reason_code"
    }}
    paths.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with paths.log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": event, **allowed}, sort_keys=True) + "\n")
    paths.log_path.chmod(0o600)


class LinuxProcessInspector:
    def is_alive(self, pid: int) -> bool:
        return Path(f"/proc/{pid}").is_dir()
    def pgid(self, pid: int) -> int:
        return os.getpgid(pid)
    def start_token(self, pid: int) -> str:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]
    def executable(self, pid: int) -> str:
        return os.readlink(f"/proc/{pid}/exe")
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
    )
    try:
        append_agent_log(paths, "run.start", task_id=task_id, state="starting")
        handle = provider.start(start_spec)
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _raise_termination)
        sigterm_installed = True
        session = provider.create_session(handle, TaskSpec(task_id=task_id, prompt=prompt))
        owned = provider.ownership(handle)
        write_runtime_state(paths, AgentRuntimeState(
            schema_version=1, owner_uid=os.getuid(), pid=owned["pid"], pgid=owned["pgid"],
            process_start_token=owned["start_token"], executable=owned["executable"],
            workspace_hash=hashlib.sha256(str(workspace).encode()).hexdigest(),
            task_id=task_id, session_id=session.session_id, provider_version=handle.provider_version,
            started_at=datetime.now(timezone.utc).isoformat(), state="running",
        ))
        for event in provider.stream_events(handle, session):
            reason = event.details.get("reason_code")
            append_agent_log(paths, "provider.event", task_id=event.task_id,
                             session_id=event.session_id, provider_version=event.provider_version,
                             state=event.state.value, reason_code=str(reason) if reason else "")
            if event.type is EventType.TASK_FINISHED: terminal = event.state.value
            elif event.type is EventType.TASK_BLOCKED: terminal = "blocked"
        return terminal
    except (KeyboardInterrupt, _TerminationRequested):
        terminal = "cancelled"; return terminal
    except Exception as exc:
        append_agent_log(paths, "run.error", task_id=task_id, state="failed", reason_code=type(exc).__name__)
        raise AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider execution failed") from exc
    finally:
        if handle is not None and session is not None:
            try: provider.cancel(handle, session)
            except Exception: append_agent_log(paths, "abort.error", task_id=task_id, state=terminal, reason_code="ABORT_FAILED")
        if handle is not None:
            try:
                provider.stop(handle)
            except Exception as exc:
                stop_error = exc
                append_agent_log(paths, "stop.error", task_id=task_id, state=terminal, reason_code="STOP_UNCONFIRMED")
        if handle is None or stop_error is None:
            paths.runtime_path.unlink(missing_ok=True)
        if sigterm_installed:
            signal.signal(signal.SIGTERM, previous_sigterm)
        append_agent_log(paths, "run.stop", task_id=task_id, state=terminal)
        if stop_error is not None:
            raise AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider stop was not confirmed") from stop_error


@agent_app.command()
def doctor(output: str = typer.Option("text", "--format")) -> None:
    """Check local endpoint-agent prerequisites."""
    try:
        _config()
        executable = shutil.which("opencode")
        if executable is None:
            raise AgentCommandFailure(AgentErrorCode.PROVIDER_UNAVAILABLE, "opencode is not installed")
        _emit(
            ok=True,
            code=AgentErrorCode.OK,
            message="local prerequisites available",
            data={"opencode": executable},
            output=output,
        )
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
    prompt_file: str = typer.Option(..., "--prompt-file"),
    output: str = typer.Option("text", "--format"),
) -> None:
    """Run an endpoint-agent task locally."""
    try:
        paths, config = _config()
        resolved = _workspace(workspace, config)
        result = _run_local_task(resolved, _read_prompt(prompt_file), paths, config)
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
        elif validate_owned_process(state, LinuxProcessInspector()):
            data = {"state": state.state, "task_id": state.task_id, "session_id": state.session_id}
        else:
            paths.runtime_path.unlink(missing_ok=True); data = {"state": "stopped"}
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
        content = log_text.splitlines()[-lines:]
    _emit(ok=True, code=AgentErrorCode.OK, message="logs", data={"lines": content}, output=output)
