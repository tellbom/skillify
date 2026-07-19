"""Endpoint-local admission and model-call limits for one Shogun team."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class ConcurrencyPolicy:
    max_active_teams: int = 1
    max_active_workers: int = 3
    max_parallel_model_calls: int = 2
    max_user_tasks: int = 1
    max_team_duration_minutes: int = 120
    feed_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        integers = (
            self.max_active_teams, self.max_active_workers, self.max_parallel_model_calls,
            self.max_user_tasks, self.max_team_duration_minutes,
        )
        if any(type(value) is not int or value < 1 for value in integers):
            raise ValueError("Shogun concurrency limits must be positive integers")
        if self.max_active_teams != 1:
            raise ValueError("phase-one Shogun supports one active team per endpoint")
        if self.max_parallel_model_calls > self.max_active_workers:
            raise ValueError("model-call concurrency cannot exceed active workers")
        if not math.isfinite(self.feed_interval_seconds) or self.feed_interval_seconds <= 0:
            raise ValueError("Shogun feed interval must be positive")


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    queued: bool
    reason: str


class TeamConcurrency:
    def __init__(self, policy: ConcurrencyPolicy) -> None:
        self.policy = policy
        self.active_team: str | None = None
        self.active_user: str | None = None
        self.active_workers: set[str] = set()
        self.model_calls: set[str] = set()
        self.started_at: datetime | None = None
        self.next_feed_at: datetime | None = None

    def admit_team(self, task_id: str, user_id: str, now: datetime) -> AdmissionDecision:
        self._utc(now)
        if self.active_team is not None:
            return AdmissionDecision(False, True, "endpoint-team-limit")
        self.active_team = task_id
        self.active_user = user_id
        self.started_at = now
        self.next_feed_at = now
        return AdmissionDecision(True, False, "admitted")

    def admit_worker(self, worker_id: str) -> bool:
        if len(self.active_workers) >= self.policy.max_active_workers:
            return False
        self.active_workers.add(worker_id)
        return True

    def begin_model_call(self, worker_id: str, now: datetime) -> AdmissionDecision:
        self._utc(now)
        if worker_id not in self.active_workers:
            return AdmissionDecision(False, True, "worker-not-active")
        if len(self.model_calls) >= self.policy.max_parallel_model_calls:
            return AdmissionDecision(False, True, "model-concurrency-limit")
        if self.next_feed_at is not None and now < self.next_feed_at:
            return AdmissionDecision(False, True, "feed-paced")
        self.model_calls.add(worker_id)
        self.next_feed_at = now + timedelta(seconds=self.policy.feed_interval_seconds)
        return AdmissionDecision(True, False, "admitted")

    def finish_model_call(self, worker_id: str) -> None:
        self.model_calls.discard(worker_id)

    def backoff_seconds(self, status_code: int, attempt: int) -> float:
        if status_code not in {429, 503}:
            return 0.0
        return min(60.0, 2.0 ** max(0, min(attempt, 6)))

    def timed_out(self, now: datetime) -> bool:
        self._utc(now)
        return self.started_at is not None and now >= self.started_at + timedelta(
            minutes=self.policy.max_team_duration_minutes,
        )

    def release(self) -> None:
        self.active_team = None
        self.active_user = None
        self.active_workers.clear()
        self.model_calls.clear()
        self.started_at = None
        self.next_feed_at = None

    @staticmethod
    def _utc(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("Shogun concurrency timestamps must be UTC-aware")
