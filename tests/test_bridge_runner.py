from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading

from skillify.agent.fake_provider import FakeProvider
from skillify.agent.provider import (
    ModelRuntimeConfig, ProviderHandle, ProviderRecovery, ProviderResult, ProviderSession,
    ProviderStartSpec,
)
from skillify.agent.events import EventType, TaskEvent, TaskState
from skillify.agent.runner import TaskRunner
from skillify.cli.bridge_cmd import BridgeLoop, LocalOutbox, RoutedBridgeRunner
from skillify.tasks.protocol import TaskEnvelope
from skillify.tasks.reporting import TaskEventReporter
from skillify.tasks.mcp_injection import McpPackageConfig


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

    def confirm_scope(self, task_id, nonce, state_version, purpose, aliases):
        raise AssertionError("non-App tasks must not request App scope confirmation")


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


def test_task_runner_cancels_the_active_provider_and_reports_cancelled(tmp_path: Path) -> None:
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")
    started = threading.Event()
    released = threading.Event()
    handle = ProviderHandle("handle-1", "opencode", "1.0.0", "http://127.0.0.1", 10)
    session = ProviderSession("task-1", "session-1", handle.handle_id)

    class BlockingProvider:
        def start(self, spec):
            return handle

        def create_session(self, value, spec):
            return session

        def stream_events(self, value, active_session):
            started.set()
            released.wait(2)
            return iter(())

        def cancel(self, value, active_session):
            released.set()
            return ProviderResult(TaskState.CANCELLED)

        def stop(self, value):
            return ProviderResult(TaskState.SUCCEEDED)

    workspace = tmp_path / "repo"; workspace.mkdir()
    runner = TaskRunner(
        {"opencode": BlockingProvider()},
        lambda _: ProviderStartSpec(workspace, (workspace,), tmp_path / "config", ModelRuntimeConfig()),
        outbox,
    )
    worker = threading.Thread(target=lambda: runner.run(_envelope(), state_version=2))
    worker.start()
    assert started.wait(1)
    assert runner.cancel("task-1") is True
    worker.join(2)

    assert not worker.is_alive()
    assert [item["payload"]["eventType"] for item in outbox.pending()] == ["task.cancelled"]


def test_task_runner_stops_provider_when_session_creation_fails(tmp_path: Path) -> None:
    handle = ProviderHandle("handle-1", "opencode", "1.0.0", "http://127.0.0.1", 10)

    class FailingProvider:
        stopped = False

        def start(self, spec):
            return handle

        def create_session(self, value, spec):
            raise RuntimeError("session failed")

        def stop(self, value):
            self.stopped = True
            return ProviderResult(TaskState.SUCCEEDED)

    provider = FailingProvider()
    workspace = tmp_path / "repo"; workspace.mkdir()
    runner = TaskRunner(
        {"opencode": provider},
        lambda _: ProviderStartSpec(workspace, (workspace,), tmp_path / "config", ModelRuntimeConfig()),
        LocalOutbox(tmp_path / "outbox.jsonl"),
    )

    import pytest
    with pytest.raises(RuntimeError, match="session failed"):
        runner.run(_envelope(), state_version=2)
    assert provider.stopped is True


def test_runtime_catalog_is_always_injected_and_issue_question_blocks(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"; workspace.mkdir()
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")
    handle = ProviderHandle("handle-1", "opencode", "1.0.0", "http://127.0.0.1", 10)
    session = ProviderSession("task-1", "session-1", handle.handle_id)

    class QuestionProvider:
        start_spec = None
        prompt = ""

        def start(self, spec):
            self.start_spec = spec
            return handle

        def create_session(self, value, spec):
            self.prompt = spec.prompt
            return session

        def stream_events(self, value, active_session):
            yield TaskEvent(
                "task-1", "session-1", "opencode", "1.0.0", 1, 1, NOW,
                EventType.TOOL_COMPLETED, TaskState.RUNNING,
                {"sequence": 1, "tool_name": "forgejo_forgejo_ask_question"},
            )
            raise AssertionError("runner must stop after a blocking Issue question")

        def stop(self, value):
            return ProviderResult(TaskState.SUCCEEDED)

    provider = QuestionProvider()
    catalog = McpPackageConfig(
        "catalog", "skillctl", ("mcp", "serve", "catalog"), {},
        ("skills.search", "skills.load"), 100,
    )
    runner = TaskRunner(
        {"opencode": provider},
        lambda _: ProviderStartSpec(workspace, (workspace,), tmp_path / "config", ModelRuntimeConfig()),
        outbox, mcp_catalog={"catalog": catalog}, always_mcp=("catalog",),
    )

    runner.run(_envelope(), state_version=2)

    assert provider.start_spec is not None
    assert "catalog" in provider.start_spec.mcp_servers
    assert "skills.search" in provider.prompt and "Do not ask the user to choose" in provider.prompt
    assert [item["payload"]["eventType"] for item in outbox.pending()] == ["task.blocked"]
