"""Fixed-case replay gate for workflow release stability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ReplayGateResult:
    stable: bool
    baseline_pass_rate: float
    candidate_pass_rate: float
    missing_cases: tuple[str, ...]
    failed_cases: tuple[str, ...]


@dataclass(frozen=True)
class ReplayGate:
    case_ids: tuple[str, ...]
    baseline_pass_rate: float

    def __post_init__(self) -> None:
        if not self.case_ids or len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("replay case ids must be non-empty and unique")
        if not 0 <= self.baseline_pass_rate <= 1:
            raise ValueError("baseline pass rate must be between 0 and 1")

    def evaluate(self, outcomes: Mapping[str, bool]) -> ReplayGateResult:
        if any(type(value) is not bool for value in outcomes.values()):
            raise ValueError("replay outcomes must be booleans")
        missing = tuple(case_id for case_id in self.case_ids if case_id not in outcomes)
        failed = tuple(case_id for case_id in self.case_ids if outcomes.get(case_id) is False)
        passed = sum(outcomes.get(case_id) is True for case_id in self.case_ids)
        rate = passed / len(self.case_ids)
        return ReplayGateResult(
            stable=not missing and rate >= self.baseline_pass_rate,
            baseline_pass_rate=self.baseline_pass_rate,
            candidate_pass_rate=rate,
            missing_cases=missing,
            failed_cases=failed,
        )
