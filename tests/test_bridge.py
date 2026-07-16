from __future__ import annotations

from pathlib import Path

from skillify.cli.bridge_cmd import (
    BridgeLoop,
    BridgeTransportError,
    LocalOutbox,
)


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


def test_pull_loop_uses_exponential_backoff_then_resets(tmp_path: Path) -> None:
    transport = FakeTransport([
        BridgeTransportError("offline"),
        BridgeTransportError("offline"),
        ([{"taskId": "task-1"}], "cursor-1"),
        ([], "cursor-2"),
    ])
    sleeps: list[float] = []
    loop = BridgeLoop(
        transport, LocalOutbox(tmp_path / "outbox.jsonl"),
        sleeper=sleeps.append, initial_backoff=1, max_backoff=8,
    )

    loop.run(max_polls=4)

    assert sleeps == [1, 2]
    assert transport.cursors == [None, None, None, "cursor-1"]
    assert loop.cursor == "cursor-2"


def test_pulled_task_is_enqueued_idempotently_without_task_body(tmp_path: Path) -> None:
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")
    transport = FakeTransport([
        ([{"taskId": "task-1", "parameters": {"issueId": "secret-ish"}}], "c1"),
        ([{"taskId": "task-1"}], "c2"),
    ])
    loop = BridgeLoop(transport, outbox, sleeper=lambda _: None)

    loop.run(max_polls=2)

    assert outbox.pending() == ({
        "eventId": "task-received:task-1",
        "payload": {"taskId": "task-1", "type": "task.received"},
    },)


def test_local_outbox_deduplicates_event_ids(tmp_path: Path) -> None:
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")
    assert outbox.enqueue("event-1", {"type": "task.received"}) is True
    assert outbox.enqueue("event-1", {"type": "different"}) is False
    assert len(outbox.pending()) == 1
