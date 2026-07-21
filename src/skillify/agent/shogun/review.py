"""Structured review report, verdict, and gate checker for the gunshi pane.

``ReviewGate.check`` is a pure data-validation gate: given a structured
``ReviewReport``, it evaluates whether the reviewed work passes, needs rework,
or should be rejected outright.  It does **not** schedule agents, modify code,
send events, or manage state -- those are the caller's responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewReport:
    """Structured review output from the gunshi pane.

    All check fields must be **True** for a full pass.  See
    :meth:`ReviewGate.check` for the exact verdict rules.
    """

    worker_ids_reviewed: tuple[str, ...]
    diff_consistent: bool
    scope_ok: bool
    overlaps_handled: bool
    no_ours_theirs: bool
    no_unrelated_changes: bool
    tests_cover: bool
    clean_files: bool
    integration_complete: bool
    no_remote_credentials: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewVerdict:
    """The outcome of a gate check.

    Attributes:
        passed: ``True`` when the review passes the gate.
        reason:  Human-readable explanation when *passed* is ``False``, or
            ``None`` when passed.
        rework:  **Only meaningful when *passed* is ``False``**.  ``True``
            means the work can be reworked and resubmitted; ``False`` means
            a hard reject (structural / compliance failure).
    """

    passed: bool
    reason: str | None
    rework: bool


_REWORK_FIELDS: tuple[tuple[str, str], ...] = (
    ("diff_consistent", "diff is not consistent with work-package scope"),
    ("scope_ok", "changed files exceed allowed scope"),
    ("overlaps_handled", "file overlaps between workers are not handled"),
    ("no_ours_theirs", "final diff contains 'ours/theirs' conflict markers"),
    ("no_unrelated_changes", "diff includes changes unrelated to the work package"),
    ("tests_cover", "test coverage is insufficient"),
    ("clean_files", "uncommitted files or build artifacts present"),
)

_REJECT_FIELDS: tuple[tuple[str, str], ...] = (
    ("integration_complete", "integration commit does not include all approved changes"),
    ("no_remote_credentials", "remote credentials leaked in the diff"),
)


class ReviewGate:
    """Pure validation gate for structured review reports.

    All methods are ``@staticmethod`` -- no instance state, no lifecycle, no
    agent scheduling.
    """

    @staticmethod
    def check(report: ReviewReport) -> ReviewVerdict:
        """Verify a structured review report and produce a verdict.

        Returns :class:`ReviewVerdict`:

        * ``passed=True`` -- gate passed.
        * ``passed=False, rework=True`` -- needs rework, can be resubmitted.
        * ``passed=False, rework=False`` -- hard reject (structural / compliance).

        All 10 check fields must be ``True`` for a pass.  Specific failures map
        to rework vs. reject (see task brief).
        """
        failures: list[str] = []

        # --- Hard-reject checks (rework=False) ------------------------------------
        if not report.worker_ids_reviewed:
            failures.append(
                "worker_ids_reviewed: no workers were reviewed (empty list)",
            )
        for field_name, msg in _REJECT_FIELDS:
            if not getattr(report, field_name):
                failures.append(f"{field_name}: {msg}")

        # --- Rework checks (rework=True) ------------------------------------------
        rework_failures: list[str] = []
        for field_name, msg in _REWORK_FIELDS:
            if not getattr(report, field_name):
                rework_failures.append(f"{field_name}: {msg}")

        if not failures and not rework_failures:
            return ReviewVerdict(passed=True, reason=None, rework=False)

        is_hard_reject = bool(failures)  # populated only by reject-tier checks above
        failures.extend(rework_failures)
        reason = "; ".join(failures)

        return ReviewVerdict(passed=False, reason=reason, rework=not is_hard_reject)
