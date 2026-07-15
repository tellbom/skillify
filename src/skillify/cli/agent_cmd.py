from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

import typer
import yaml

from skillify.common.config import (
    AgentLocalConfig,
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


def _run_local_task(workspace: Path, prompt: str) -> str:
    if shutil.which("opencode") is None:
        raise AgentCommandFailure(AgentErrorCode.PROVIDER_UNAVAILABLE, "opencode is not installed")
    raise AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider adapter is not installed")


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
        _, config = _config()
        resolved = _workspace(workspace, config)
        result = _run_local_task(resolved, _read_prompt(prompt_file))
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
        paths, _ = _config()
        data = (
            json.loads(paths.runtime_path.read_text(encoding="utf-8"))
            if paths.runtime_path.is_file()
            else {"state": "stopped"}
        )
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("state"), str)
            or not data["state"].strip()
        ):
            raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "runtime state is invalid")
        _emit(ok=True, code=AgentErrorCode.OK, message=str(data["state"]), data=data, output=output)
    except AgentCommandFailure as exc:
        _fail(exc, output)
    except (json.JSONDecodeError, KeyError, OSError):
        _fail(AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "runtime state is invalid"), output)


@agent_app.command()
def stop(output: str = typer.Option("text", "--format")) -> None:
    """Stop the owned local provider process."""
    paths = load_agent_paths()
    try:
        paths.runtime_path.unlink(missing_ok=True)
    except OSError:
        _fail(AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "runtime state is invalid"), output)
    _emit(ok=True, code=AgentErrorCode.OK, message="stopped", data={"state": "stopped"}, output=output)


@agent_app.command()
def logs(
    lines: int = typer.Option(100, "--lines", min=1, max=10000),
    output: str = typer.Option("text", "--format"),
) -> None:
    """Read redacted local lifecycle logs."""
    path = load_agent_paths().log_path
    try:
        content = path.read_text(encoding="utf-8").splitlines()[-lines:] if path.is_file() else []
    except OSError:
        _fail(AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "agent logs are invalid"), output)
    _emit(ok=True, code=AgentErrorCode.OK, message="logs", data={"lines": content}, output=output)
