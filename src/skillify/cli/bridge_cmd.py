"""Opt-in outbound endpoint bridge and local outbox."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import requests
import typer

from skillify.common.config import load_agent_local_config, load_agent_paths, load_config


bridge_app = typer.Typer(help="Manage the opt-in outbound endpoint bridge.", no_args_is_help=True)


class BridgeTransportError(RuntimeError):
    pass


class BridgeTransport(Protocol):
    def pull(self, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]: ...
    def confirm(self, task_id: str, nonce: str, state_version: int) -> int: ...


class BridgeRunner(Protocol):
    def run(self, envelope, *, state_version: int) -> int: ...


class BridgeReporter(Protocol):
    def flush(self) -> int: ...


class RoutedBridgeRunner:
    """Keep fixed Code Map actions out of the Agent provider execution path."""

    def __init__(self, agent_runner: BridgeRunner, codemap_factory: Callable[[], BridgeRunner]) -> None:
        self.agent_runner = agent_runner
        self.codemap_factory = codemap_factory

    def run(self, envelope, *, state_version: int) -> int:
        from skillify.codemap.visualizer import CODEMAP_WORKFLOWS
        if envelope.workflow_id in CODEMAP_WORKFLOWS:
            return self.codemap_factory().run(envelope, state_version=state_version)
        return self.agent_runner.run(envelope, state_version=state_version)


class HttpBridgeTransport:
    def __init__(self, server_url: str, token: str, *, session: requests.Session | None = None) -> None:
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.session = session or requests.Session()

    def pull(self, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        try:
            response = self.session.get(
                f"{self.server_url}/api/endpoint/tasks/pull",
                headers={"Authorization": f"Bearer {self.token}"},
                params={} if cursor is None else {"cursor": cursor},
                timeout=30,
            )
            response.raise_for_status()
            value = response.json()
            tasks = value.get("tasks", [])
            if type(tasks) is not list or any(type(item) is not dict for item in tasks):
                raise ValueError("tasks must be a list of objects")
            next_cursor = value.get("nextCursor")
            if next_cursor is not None and type(next_cursor) is not str:
                raise ValueError("nextCursor must be a string")
            return tasks, next_cursor
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise BridgeTransportError("endpoint task pull failed") from exc

    def confirm(self, task_id: str, nonce: str, state_version: int) -> int:
        try:
            response = self.session.post(
                f"{self.server_url}/api/endpoint/tasks/{task_id}/confirm",
                headers={"Authorization": f"Bearer {self.token}"},
                json={"nonce": nonce, "stateVersion": state_version}, timeout=10,
            )
            response.raise_for_status()
            return int(response.json()["stateVersion"])
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise BridgeTransportError("endpoint task confirmation failed") from exc


class LocalOutbox:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _records(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        records = []
        for line in lines:
            value = json.loads(line)
            if type(value) is not dict or type(value.get("eventId")) is not str:
                raise ValueError("outbox record is invalid")
            records.append(value)
        return records

    def enqueue(self, event_id: str, payload: dict[str, Any]) -> bool:
        if not event_id or type(payload) is not dict:
            raise ValueError("outbox event requires id and object payload")
        records = self._records()
        if any(record["eventId"] == event_id for record in records):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        records.append({"eventId": event_id, "payload": payload})
        self.path.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )
        self.path.chmod(0o600)
        return True

    def pending(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._records())

    def acknowledge(self, event_id: str) -> bool:
        records = self._records()
        kept = [record for record in records if record["eventId"] != event_id]
        if len(kept) == len(records):
            return False
        self.path.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in kept),
            encoding="utf-8",
        )
        return True


class BridgeLoop:
    def __init__(
        self,
        transport: BridgeTransport,
        outbox: LocalOutbox,
        runner: BridgeRunner,
        reporter: BridgeReporter,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        self.transport = transport
        self.outbox = outbox
        self.runner = runner
        self.reporter = reporter
        self.sleeper = sleeper
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.cursor: str | None = None
        self._next_backoff = initial_backoff
        self._executed: set[str] = set()

    def poll(self) -> bool:
        try:
            tasks, cursor = self.transport.pull(self.cursor)
        except BridgeTransportError:
            delay = self._next_backoff
            self._next_backoff = min(self.max_backoff, delay * 2)
            self.sleeper(delay)
            return False
        self._next_backoff = self.initial_backoff
        self.cursor = cursor
        from skillify.tasks.protocol import TaskEnvelope
        for task in tasks:
            envelope = TaskEnvelope.from_dict(task)
            if envelope.task_id in self._executed:
                self.reporter.flush()
                continue
            state_version = self.transport.confirm(
                envelope.task_id, envelope.nonce, envelope.state_version,
            )
            self.runner.run(envelope, state_version=state_version)
            self._executed.add(envelope.task_id)
            self.reporter.flush()
        return True

    def run(self, *, max_polls: int | None = None) -> None:
        count = 0
        while max_polls is None or count < max_polls:
            self.poll()
            count += 1


@dataclass(frozen=True)
class BridgeRuntimeState:
    pid: int
    server_url: str
    started_at: str
    state: str = "running"


def _paths() -> tuple[Path, Path]:
    state_dir = load_agent_paths().state_dir
    return state_dir / "bridge.json", state_dir / "outbox.jsonl"


def _write_state(path: Path, state: BridgeRuntimeState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(asdict(state), sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def _read_state(path: Path) -> BridgeRuntimeState | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    return BridgeRuntimeState(**value)


def _resolve_connection(server: str | None, token_env: str) -> tuple[str, str]:
    server_url = server or load_config().web_base_url
    token = os.environ.get(token_env)
    if not server_url or not token:
        raise typer.BadParameter("server URL and endpoint bearer token are required")
    return server_url, token


def connect(
    server: str | None = typer.Option(None, "--server"),
    token_env: str = typer.Option("SKILLIFY_ENDPOINT_TOKEN", "--token-env"),
    once: bool = typer.Option(False, "--once", help="Poll once and exit."),
) -> None:
    """Connect this endpoint to the Skillify control plane using outbound polling."""
    server_url, token = _resolve_connection(server, token_env)
    state_path, outbox_path = _paths()
    state = BridgeRuntimeState(os.getpid(), server_url, datetime.now(timezone.utc).isoformat())
    _write_state(state_path, state)
    try:
        transport = HttpBridgeTransport(server_url, token)
        outbox = LocalOutbox(outbox_path)
        BridgeLoop(
            transport, outbox, _build_runner(outbox), _build_reporter(server_url, token, outbox),
        ).run(
            max_polls=1 if once else None,
        )
    except KeyboardInterrupt:
        pass
    finally:
        state_path.unlink(missing_ok=True)


def _build_runner(outbox: LocalOutbox):
    from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec
    from skillify.agent.providers.opencode import OpenCodeProvider
    from skillify.agent.providers.claudecode import ClaudeCodeProvider
    from skillify.agent.runner import TaskRunner
    from skillify.tasks.protocol import TaskEnvelope
    from skillify.tasks.mcp_injection import McpPackageConfig

    paths = load_agent_paths(); config = load_agent_local_config(paths)
    aliases = dict(config.workspace_aliases)
    for raw in config.allowed_workspaces:
        aliases.setdefault(Path(raw).name, raw)
    runtime = ModelRuntimeConfig(
        config.model_provider or "", config.model_endpoint or "", config.model_name or "",
        config.allowed_model_hosts, config.credential_env_names,
    )

    def start_spec(envelope: TaskEnvelope) -> ProviderStartSpec:
        raw = aliases.get(envelope.workspace_alias)
        if raw is None:
            raise ValueError("workspace alias is not configured on this endpoint")
        workspace = Path(raw).resolve(strict=True)
        endpoint_name = "ANTHROPIC_BASE_URL" if envelope.preferred_cli == "claude-code" else "OPENCODE_BASE_URL"
        base_commit = ""
        repository_root = None
        if envelope.runtime == "shogun" and envelope.execution_mode == "team":
            status = subprocess.run(
                ["git", "-C", str(workspace), "status", "--porcelain"],
                capture_output=True, text=True, check=False,
            )
            if status.returncode != 0:
                raise ValueError(f"failed to inspect workspace git status: {status.stderr.strip()}")
            if status.stdout.strip():
                raise ValueError(
                    "workspace has uncommitted changes; team execution requires a clean workspace"
                )
            head = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=False,
            )
            if head.returncode != 0:
                raise ValueError(f"failed to resolve workspace HEAD commit: {head.stderr.strip()}")
            base_commit = head.stdout.strip()
            repository_root = workspace
        return ProviderStartSpec(
            workspace, (workspace,), paths.cache_dir / envelope.runtime / envelope.task_id, runtime,
            execution_mode=envelope.execution_mode,
            preferred_cli=envelope.preferred_cli,
            team_policy=dict(envelope.team_policy),
            work_packages=tuple(dict(item) for item in envelope.work_packages),
            network_environment={endpoint_name: runtime.endpoint} if envelope.runtime == "shogun" else {},
            network_allowlist=runtime.allowed_endpoint_hosts,
            base_commit=base_commit,
            repository_root=repository_root,
        )

    providers = {"opencode": OpenCodeProvider(), "claude-code": ClaudeCodeProvider()}
    if config.shogun_team_enabled:
        from skillify.agent.providers.shogun import ShogunProvider
        required = (
            config.shogun_manifest_path, config.shogun_artifact_path, config.shogun_install_root,
        )
        if not all(required):
            raise ValueError("enabled Shogun team runtime requires manifest, artifact, and install root")
        providers["shogun"] = ShogunProvider(
            manifest_path=Path(config.shogun_manifest_path or ""),
            artifact_path=Path(config.shogun_artifact_path or ""),
            install_root=Path(config.shogun_install_root or ""),
            cache_root=paths.cache_dir / "shogun",
        )
    agent_runner = TaskRunner(
        providers,
        start_spec, outbox,
        mcp_catalog={"codegraph": McpPackageConfig(
            "codegraph", "codegraph", ("serve", "--mcp"),
            {"CODEGRAPH_NO_DOWNLOAD": "1", "CODEGRAPH_TELEMETRY": "0", "CODEGRAPH_PROJECT_ROOT": "{workspace}"},
            ("codegraph_explore",), 4000,
        )},
    )
    return RoutedBridgeRunner(agent_runner, lambda: _build_codemap_runner(outbox))


def _build_codemap_runner(outbox: LocalOutbox):
    from skillify.codemap.task_runner import CodemapTaskRunner
    from skillify.codemap.visualizer import GitNexusVisualizer, load_manifest, resolve_workspace_alias

    paths = load_agent_paths()
    config = load_agent_local_config(paths)
    aliases = dict(config.workspace_aliases)
    for raw in config.allowed_workspaces:
        aliases.setdefault(Path(raw).name, raw)
    manifest_default = Path(__file__).resolve().parents[3] / "infra" / "offline" / "gitnexus-visualizer-manifest.json"
    manifest_path = Path(os.environ.get("SKILLIFY_GITNEXUS_MANIFEST", manifest_default))
    runtime_raw = os.environ.get(
        "SKILLIFY_GITNEXUS_ROOT", "/opt/skillify/codemap/gitnexus/1.6.9",
    )
    visualizer = GitNexusVisualizer(
        manifest=load_manifest(manifest_path), runtime_root=Path(runtime_raw),
        state_root=paths.state_dir / "codemap-visualizer",
    )
    return CodemapTaskRunner(
        visualizer, lambda alias: resolve_workspace_alias(alias, aliases), outbox,
    )


def _build_reporter(server_url: str, token: str, outbox: LocalOutbox):
    from skillify.tasks.reporting import HttpEventEndpoint, TaskEventReporter
    return TaskEventReporter(outbox, HttpEventEndpoint(server_url, token))


@bridge_app.command("start")
def start(
    server: str | None = typer.Option(None, "--server"),
    token_env: str = typer.Option("SKILLIFY_ENDPOINT_TOKEN", "--token-env"),
    once: bool = typer.Option(False, "--once"),
) -> None:
    """Start the bridge in the foreground (default) or perform one poll."""
    connect(server, token_env, once)


@bridge_app.command("status")
def status() -> None:
    """Show the locally recorded bridge state."""
    state_path, outbox_path = _paths()
    state = _read_state(state_path)
    typer.echo(json.dumps({
        "state": "stopped" if state is None else state.state,
        "pid": None if state is None else state.pid,
        "pendingOutbox": len(LocalOutbox(outbox_path).pending()),
    }, sort_keys=True))


@bridge_app.command("stop")
def stop() -> None:
    """Request termination of the locally recorded foreground bridge."""
    state_path, _ = _paths()
    state = _read_state(state_path)
    if state is not None:
        try:
            os.kill(state.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        state_path.unlink(missing_ok=True)
    typer.echo(json.dumps({"state": "stopped"}, sort_keys=True))
