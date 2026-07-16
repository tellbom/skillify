from __future__ import annotations

from skillify.evals import ReplayGate, aggregate_task_metrics


def test_metrics_aggregate_task_outcomes_tests_reasons_and_deduplicate_events() -> None:
    events = [
        {"eventId": "e1", "taskId": "t1", "eventType": "test.completed", "testSummary": {"passed": 4, "failed": 1}},
        {"eventId": "e2", "taskId": "t1", "eventType": "task.succeeded"},
        {"eventId": "e3", "taskId": "t2", "eventType": "task.rejected", "reasonCode": "PERMISSION_DENIED"},
        {"eventId": "e4", "taskId": "t3", "eventType": "task.rolled_back", "reasonCode": "TEST_FAILED"},
        {"eventId": "e4", "taskId": "t3", "eventType": "task.rolled_back", "reasonCode": "TEST_FAILED"},
    ]

    metrics = aggregate_task_metrics(events)

    assert metrics["completedTasks"] == 3
    assert metrics["successRate"] == 1 / 3
    assert metrics["rejectionRate"] == 1 / 3
    assert metrics["rollbackRate"] == 1 / 3
    assert metrics["testPassRate"] == 0.8
    assert metrics["blockedReasons"] == {"PERMISSION_DENIED": 1, "TEST_FAILED": 1}
    assert metrics["eventCount"] == 4


def test_replay_gate_requires_all_fixed_cases_and_baseline_rate() -> None:
    gate = ReplayGate(("bugfix-python", "feature-vue", "review-go"), baseline_pass_rate=2 / 3)

    stable = gate.evaluate({"bugfix-python": True, "feature-vue": True, "review-go": False})
    below = gate.evaluate({"bugfix-python": True, "feature-vue": False, "review-go": False})
    missing = gate.evaluate({"bugfix-python": True, "feature-vue": True})

    assert stable.stable is True
    assert stable.candidate_pass_rate == 2 / 3
    assert below.stable is False
    assert missing.stable is False
    assert missing.missing_cases == ("review-go",)


def test_empty_metrics_do_not_invent_percentages() -> None:
    metrics = aggregate_task_metrics([])
    assert metrics["completedTasks"] == 0
    assert metrics["successRate"] == metrics["testPassRate"] == 0.0
