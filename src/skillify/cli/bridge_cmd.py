"""Opt-in outbound endpoint bridge and local outbox."""

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import requests
import typer

from skillify.common.config import load_agent_paths, load_config


bridge_app = typer.Typer(help="Manage the opt-in outbound endpoint bridge.", no_args_is_help=True)


class BridgeTransportError(RuntimeError):
    pass


class BridgeTransport(Protocol):
    def pull(self, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]: ...


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


class BridgeLoop:
    def __init__(
        self,
        transport: BridgeTransport,
        outbox: LocalOutbox,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        self.transport = transport
        self.outbox = outbox
        self.sleeper = sleeper
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.cursor: str | None = None
        self._next_backoff = initial_backoff

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
        for task in tasks:
            task_id = task.get("taskId")
            if type(task_id) is not str or not task_id:
                raise ValueError("pulled task requires taskId")
            self.outbox.enqueue(
                f"task-received:{task_id}",
                {"type": "task.received", "taskId": task_id},
            )
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
    token_env: str = typer.Option("SKILLIFY_AGENT_TOKEN", "--token-env"),
    once: bool = typer.Option(False, "--once", help="Poll once and exit."),
) -> None:
    """Connect this endpoint to the Skillify control plane using outbound polling."""
    server_url, token = _resolve_connection(server, token_env)
    state_path, outbox_path = _paths()
    state = BridgeRuntimeState(os.getpid(), server_url, datetime.now(timezone.utc).isoformat())
    _write_state(state_path, state)
    try:
        BridgeLoop(HttpBridgeTransport(server_url, token), LocalOutbox(outbox_path)).run(
            max_polls=1 if once else None,
        )
    except KeyboardInterrupt:
        pass
    finally:
        state_path.unlink(missing_ok=True)


@bridge_app.command("start")
def start(
    server: str | None = typer.Option(None, "--server"),
    token_env: str = typer.Option("SKILLIFY_AGENT_TOKEN", "--token-env"),
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
