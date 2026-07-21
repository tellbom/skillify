"""Tests for review.py -- ReviewGate pure validation, no mocking needed."""

from __future__ import annotations

import inspect

from skillify.agent.shogun.review import ReviewGate, ReviewReport, ReviewVerdict


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _full_pass_report(**overrides: object) -> ReviewReport:
    """A ReviewReport with every check field True; override individual fields."""
    fields: dict[str, object] = {
        "worker_ids_reviewed": ("w1", "w2"),
        "diff_consistent": True,
        "scope_ok": True,
        "overlaps_handled": True,
        "no_ours_theirs": True,
        "no_unrelated_changes": True,
        "tests_cover": True,
        "clean_files": True,
        "integration_complete": True,
        "no_remote_credentials": True,
        "notes": (),
    }
    fields.update(overrides)
    return ReviewReport(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# full pass
# ---------------------------------------------------------------------------

def test_all_checks_true_passes() -> None:
    report = _full_pass_report()
    verdict = ReviewGate.check(report)
    assert verdict == ReviewVerdict(passed=True, reason=None, rework=False)


# ---------------------------------------------------------------------------
# rework-tier failures (rework=True)
# ---------------------------------------------------------------------------

def test_diff_consistent_false_is_rework() -> None:
    report = _full_pass_report(diff_consistent=False)
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is True
    assert "diff_consistent" in verdict.reason


def test_scope_ok_false_is_rework() -> None:
    report = _full_pass_report(scope_ok=False)
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is True
    assert "scope_ok" in verdict.reason


def test_overlaps_handled_false_is_rework() -> None:
    report = _full_pass_report(overlaps_handled=False)
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is True
    assert "overlaps_handled" in verdict.reason


def test_no_ours_theirs_false_is_rework() -> None:
    report = _full_pass_report(no_ours_theirs=False)
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is True
    assert "no_ours_theirs" in verdict.reason


def test_no_unrelated_changes_false_is_rework() -> None:
    report = _full_pass_report(no_unrelated_changes=False)
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is True
    assert "no_unrelated_changes" in verdict.reason


def test_tests_cover_false_is_rework() -> None:
    report = _full_pass_report(tests_cover=False)
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is True
    assert "tests_cover" in verdict.reason


def test_clean_files_false_is_rework() -> None:
    report = _full_pass_report(clean_files=False)
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is True
    assert "clean_files" in verdict.reason


# ---------------------------------------------------------------------------
# reject-tier failures (rework=False)
# ---------------------------------------------------------------------------

def test_integration_complete_false_is_reject() -> None:
    report = _full_pass_report(integration_complete=False)
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is False
    assert "integration_complete" in verdict.reason


def test_no_remote_credentials_false_is_reject() -> None:
    report = _full_pass_report(no_remote_credentials=False)
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is False
    assert "no_remote_credentials" in verdict.reason


def test_empty_worker_ids_reviewed_is_reject() -> None:
    report = _full_pass_report(worker_ids_reviewed=())
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is False
    assert "worker_ids_reviewed" in verdict.reason


# ---------------------------------------------------------------------------
# priority: reject-tier failure takes precedence over rework-tier failure
# ---------------------------------------------------------------------------

def test_reject_takes_priority_over_rework_failure() -> None:
    report = _full_pass_report(
        integration_complete=False,
        diff_consistent=False,
    )
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is False
    assert "integration_complete" in verdict.reason
    assert "diff_consistent" in verdict.reason


# ---------------------------------------------------------------------------
# multiple failures aggregated in reason
# ---------------------------------------------------------------------------

def test_multiple_rework_failures_all_in_reason() -> None:
    report = _full_pass_report(
        diff_consistent=False,
        tests_cover=False,
        clean_files=False,
    )
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is True
    assert "diff_consistent" in verdict.reason
    assert "tests_cover" in verdict.reason
    assert "clean_files" in verdict.reason


def test_multiple_reject_failures_all_in_reason() -> None:
    report = _full_pass_report(
        integration_complete=False,
        no_remote_credentials=False,
        worker_ids_reviewed=(),
    )
    verdict = ReviewGate.check(report)
    assert verdict.passed is False
    assert verdict.rework is False
    assert "integration_complete" in verdict.reason
    assert "no_remote_credentials" in verdict.reason
    assert "worker_ids_reviewed" in verdict.reason


# ---------------------------------------------------------------------------
# structural assertion: no agent-launch interface on ReviewGate
# ---------------------------------------------------------------------------

def test_review_gate_has_no_agent_launch_interface() -> None:
    members = {name for name, _ in inspect.getmembers(ReviewGate)}
    forbidden_substrings = ("agent", "spawn", "launch", "schedule", "start", "dispatch")
    public_members = {m for m in members if not m.startswith("_")}
    offending = {
        m for m in public_members
        if any(sub in m.lower() for sub in forbidden_substrings)
    }
    assert offending == set()
    # Only the documented public interface should exist.
    assert public_members == {"check"}
