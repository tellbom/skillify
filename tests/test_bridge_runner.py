from datetime import datetime, timedelta, timezone
from pathlib import Path

from skillify.agent.fake_provider import FakeProvider
from skillify.agent.provider import (
    ModelRuntimeConfig, ProviderHandle, ProviderRecovery, ProviderResult, ProviderSession,
    ProviderStartSpec,
)
from skillify.agent.events import TaskState
from skillify.agent.runner import TaskRunner
from skillify.cli.bridge_cmd import BridgeLoop, LocalOutbox, RoutedBridgeRunner
from skillify.tasks.protocol import TaskEnvelope
from skillify.tasks.reporting import TaskEventReporter


NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)


def _envelope() -> TaskEnvelope:
    return TaskEnvelope(
        task_id="task-1", endpoint_id="endpoint-1", workflow_id="evidence-bugfix",
        workflow_version="1.0.0", workspace_alias="repo", parameters={"issueReference": "BUG-42"},
        issued_at=NOW, expires_at=NOW + timedelta(minutes=5), nonce="nonce-1",
        runtime="opencode", state_version=1,
    ).sign(b"secret")


class Transport:
    def __init__(self, envelope: TaskEnvelope):
        self.envelope = envelope; self.polls = 0; self.confirmations = 0
    def pull(self, cursor):
        self.polls += 1
        return ([self.envelope.to_dict()], f"cursor-{self.polls}")
    def confirm(self, task_id, nonce, state_version):
        self.confirmations += 1
        return state_version + 1


class EventEndpoint:
    def __init__(self):
        self.online = False; self.ids = []
    def send(self, payload):
        self.ids.append(payload["eventId"])
        return self.online


def test_bridge_confirms_runs_provider_and_retries_outbox_without_reexecution(tmp_path: Path) -> None:
    workspace = (tmp_path / "repo").resolve(); workspace.mkdir()
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")
    provider = FakeProvider(clock=lambda: NOW, id_factory=iter(("handle", "session")).__next__)
    runner = TaskRunner(
        {"opencode": provider},
        lambda envelope: ProviderStartSpec(
            workspace, (workspace,), tmp_path / "config",
            ModelRuntimeConfig("fake", "https://model.internal/v1", "fake", ("model.internal",), ("TOKEN",)),
        ),
        outbox,
    )
    endpoint = EventEndpoint(); reporter = TaskEventReporter(outbox, endpoint)
    transport = Transport(_envelope())
    loop = BridgeLoop(transport, outbox, runner, reporter, sleeper=lambda _: None)

    loop.poll()
    pending_ids = [item["eventId"] for item in outbox.pending()]
    assert transport.confirmations == 1
    assert pending_ids and len(pending_ids) == len(set(pending_ids))
    endpoint.online = True
    loop.poll()
    assert transport.confirmations == 1
    assert outbox.pending() == ()
    assert provider.live_handle_count == provider.live_session_count == 0


def test_bridge_routes_codemap_without_starting_an_agent_provider() -> None:
    calls: list[str] = []

    class Runner:
        def __init__(self, name: str):
            self.name = name

        def run(self, envelope, *, state_version: int) -> int:
            calls.append(self.name)
            return state_version + 1

    envelope = _envelope()
    codemap = TaskEnvelope(
        task_id="codemap-1", endpoint_id=envelope.endpoint_id,
        workflow_id="codemap.visualization.status", workflow_version="1.0.0",
        workspace_alias=envelope.workspace_alias, parameters={}, issued_at=envelope.issued_at,
        expires_at=envelope.expires_at, nonce="codemap-nonce", runtime="codemap",
        state_version=1,
    ).sign(b"secret")
    routed = RoutedBridgeRunner(Runner("agent"), lambda: Runner("codemap"))

    assert routed.run(codemap, state_version=2) == 3
    assert calls == ["codemap"]


def test_bridge_reidentifies_existing_team_after_restart(tmp_path: Path) -> None:
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")
    handle = ProviderHandle("existing-handle", "shogun", "v5.2.0", "file:///queue", 0)
    session = ProviderSession("task-1", "existing-session", handle.handle_id)

    class RecoveringProvider:
        stopped = 0

        def recover(self, task_id):
            assert task_id == "task-1"
            return ProviderRecovery("live", handle, session)

        def start(self, spec):
            raise AssertionError("a recovered team must not be started again")

        def create_session(self, value, spec):
            raise AssertionError("a recovered session must not be recreated")

        def stream_events(self, value, recovered_session):
            assert value == handle and recovered_session == session
            return iter(())

        def stop(self, value):
            self.stopped += 1
            return ProviderResult(TaskState.SUCCEEDED)

    provider = RecoveringProvider()
    runner = TaskRunner(
        {"shogun": provider}, lambda _: (_ for _ in ()).throw(AssertionError("no new spec")), outbox,
    )
    envelope = TaskEnvelope(
        **{**_envelope().__dict__, "runtime": "shogun", "execution_mode": "team", "preferred_cli": "opencode"}
    )

    assert runner.run(envelope, state_version=2) == 2
    assert provider.stopped == 1


def test_bridge_safe_terminate_when_team_dead(tmp_path: Path) -> None:
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")

    class DeadProvider:
        def recover(self, task_id):
            return ProviderRecovery("dead")

        def start(self, spec):
            raise AssertionError("a dead recovered team must not be executed again")

    runner = TaskRunner(
        {"shogun": DeadProvider()}, lambda _: (_ for _ in ()).throw(AssertionError("no new spec")),
        outbox,
    )
    envelope = TaskEnvelope(
        **{**_envelope().__dict__, "runtime": "shogun", "execution_mode": "team", "preferred_cli": "opencode"}
    )

    assert runner.run(envelope, state_version=2) == 3
    assert outbox.pending()[0]["payload"]["reasonCode"] == "team-recovery-dead"
