"""Privacy-preserving workflow metrics from reported TaskEvent payloads."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


_TERMINAL_TYPES = frozenset({
    "task.succeeded", "task.failed", "task.rejected", "task.rolled_back",
})


def _rate(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def aggregate_task_metrics(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate deduplicated standard events; no task content fields are consumed."""
    unique: dict[str, Mapping[str, Any]] = {}
    for event in events:
        event_id = event.get("eventId")
        event_type = event.get("eventType")
        task_id = event.get("taskId")
        if not all(type(value) is str and value for value in (event_id, event_type, task_id)):
            raise ValueError("evaluation events require eventId, taskId, and eventType")
        unique.setdefault(event_id, event)

    terminal_by_task: dict[str, str] = {}
    reasons: Counter[str] = Counter()
    passed = failed = 0
    for event in unique.values():
        event_type = event["eventType"]
        task_id = event["taskId"]
        if event_type in _TERMINAL_TYPES:
            terminal_by_task[task_id] = event_type
        summary = event.get("testSummary")
        if summary is not None:
            if type(summary) is not dict:
                raise ValueError("testSummary must be an object")
            passed += int(summary.get("passed", 0))
            failed += int(summary.get("failed", 0))
        reason = event.get("reasonCode")
        if reason is not None:
            if type(reason) is not str:
                raise ValueError("reasonCode must be a string")
            reasons[reason] += 1

    completed = len(terminal_by_task)
    counts = Counter(terminal_by_task.values())
    return {
        "completedTasks": completed,
        "successRate": _rate(counts["task.succeeded"], completed),
        "rejectionRate": _rate(counts["task.rejected"], completed),
        "rollbackRate": _rate(counts["task.rolled_back"], completed),
        "testPassRate": _rate(passed, passed + failed),
        "blockedReasons": dict(sorted(reasons.items())),
        "eventCount": len(unique),
        "traceBackends": {
            "promptfoo": "pending-test-env",
            "phoenix": "pending-test-env",
        },
    }
