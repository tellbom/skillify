from __future__ import annotations

from pathlib import Path
import threading

from skillify.cli.bridge_cmd import (
    BridgeLoop,
    BridgeTransportError,
    LocalOutbox,
    _resolve_connection,
)
from skillify.common.config import AgentLocalConfig, load_agent_paths, save_agent_local_config


class FakeTransport:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.cursors: list[str | None] = []

    def pull(self, cursor: str | None):
        self.cursors.append(cursor)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def confirm(self, task_id: str, nonce: str, state_version: int) -> int:
        return state_version + 1

    def cancellation(self, task_id: str, nonce: str) -> bool:
        return False


class NoopRunner:
    def run(self, envelope, *, state_version: int) -> int:
        return state_version

    def cancel(self, task_id: str) -> bool:
        return False


def test_bridge_delivers_web_cancellation_to_active_runner(tmp_path: Path) -> None:
    envelope = {
        "taskProtocolVersion": 1,
        "taskId": "task-1", "endpointId": "endpoint-1",
        "workflowId": "evidence-bugfix", "workflowVersion": "1.0.0",
        "workspaceAlias": "repo", "parameters": {"issueReference": "BUG-42"},
        "issuedAt": "2026-07-22T00:00:00+00:00", "expiresAt": "2026-07-22T01:00:00+00:00",
        "nonce": "nonce-1", "runtime": "opencode", "mcpPackages": [], "stateVersion": 1,
        "signature": "signature",
    }

    class CancellingTransport(FakeTransport):
        def cancellation(self, task_id: str, nonce: str) -> bool:
            return True

    class BlockingRunner:
        def __init__(self):
            self.done = threading.Event(); self.cancelled = []

        def run(self, value, *, state_version: int) -> int:
            assert self.done.wait(2)
            return state_version + 1

        def cancel(self, task_id: str) -> bool:
            self.cancelled.append(task_id); self.done.set(); return True

    runner = BlockingRunner()
    transport = CancellingTransport([([envelope], "cursor-1")])
    loop = BridgeLoop(
        transport, LocalOutbox(tmp_path / "outbox.jsonl"), runner, NoopReporter(),
        sleeper=lambda _: None,
    )

    assert loop.poll() is True
    assert runner.cancelled == ["task-1"]


class NoopReporter:
    def flush(self) -> int:
        return 0


def test_pull_loop_uses_exponential_backoff_then_resets(tmp_path: Path) -> None:
    transport = FakeTransport([
        BridgeTransportError("offline"),
        BridgeTransportError("offline"),
        ([], "cursor-1"),
        ([], "cursor-2"),
    ])
    sleeps: list[float] = []
    loop = BridgeLoop(
        transport, LocalOutbox(tmp_path / "outbox.jsonl"), NoopRunner(), NoopReporter(),
        sleeper=sleeps.append, initial_backoff=1, max_backoff=8,
    )

    loop.run(max_polls=4)

    assert sleeps == [1, 2]
    assert transport.cursors == [None, None, None, "cursor-1"]
    assert loop.cursor == "cursor-2"


def test_local_outbox_deduplicates_event_ids(tmp_path: Path) -> None:
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")
    assert outbox.enqueue("event-1", {"type": "task.received"}) is True
    assert outbox.enqueue("event-1", {"type": "different"}) is False
    assert len(outbox.pending()) == 1
    assert outbox.acknowledge("event-1") is True
    assert outbox.acknowledge("event-1") is False


def test_connection_uses_skillctl_settings_and_private_token_file(
    tmp_path: Path, monkeypatch,
) -> None:
    env = {
        "SKILLIFY_AGENT_CONFIG_DIR": str(tmp_path / "config"),
        "SKILLIFY_AGENT_STATE_DIR": str(tmp_path / "state"),
        "SKILLIFY_AGENT_CACHE_DIR": str(tmp_path / "cache"),
        "SKILLIFY_AGENT_LOG_DIR": str(tmp_path / "log"),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    token_file = tmp_path / "endpoint-token"
    token_file.write_text("SKILLIFY_ENDPOINT_TOKEN=device-token\n", encoding="utf-8")
    token_file.chmod(0o600)
    save_agent_local_config(
        load_agent_paths(),
        AgentLocalConfig(
            control_plane_url="http://skillify.internal:8089",
            endpoint_token_file=str(token_file.resolve()),
        ),
    )

    assert _resolve_connection(None, "SKILLIFY_ENDPOINT_TOKEN") == (
        "http://skillify.internal:8089", "device-token",
    )
