"""Persistence for per-team worktree assignments and merge progress.

Both dataclasses here are plain data with atomic JSON read/write, following
the same pattern as ``TeamHandle`` in ``lifecycle.py`` (write to a ``.tmp``
sibling, ``chmod(0o600)``, then ``os.replace`` into place). Neither type
schedules work, watches state, or owns a second team state machine; they are
only the on-disk record of worktree assignments and merge sequencing.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class RegistryError(ValueError):
    pass


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


@dataclass(frozen=True)
class WorkerEntry:
    worker_id: str
    branch: str
    worktree: Path
    work_package_id: str
    allowed_paths: tuple[str, ...]
    state: str
    worker_commit: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "worker_id": self.worker_id,
            "branch": self.branch,
            "worktree": str(self.worktree),
            "work_package_id": self.work_package_id,
            "allowed_paths": list(self.allowed_paths),
            "worker_commit": self.worker_commit,
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorkerEntry":
        expected = {
            "worker_id", "branch", "worktree", "work_package_id",
            "allowed_paths", "worker_commit", "state",
        }
        if set(value) != expected:
            raise RegistryError("worker entry has unexpected fields")
        worker_id, branch, worktree, work_package_id, allowed_paths, worker_commit, state = (
            value["worker_id"], value["branch"], value["worktree"],
            value["work_package_id"], value["allowed_paths"],
            value["worker_commit"], value["state"],
        )
        if not isinstance(worker_id, str) or not worker_id:
            raise RegistryError("worker entry is invalid")
        if not isinstance(branch, str) or not branch:
            raise RegistryError("worker entry is invalid")
        if not isinstance(worktree, str):
            raise RegistryError("worker entry is invalid")
        if not isinstance(work_package_id, str) or not work_package_id:
            raise RegistryError("worker entry is invalid")
        if not isinstance(allowed_paths, list) or not all(
            isinstance(item, str) for item in allowed_paths
        ):
            raise RegistryError("worker entry is invalid")
        if worker_commit is not None and not isinstance(worker_commit, str):
            raise RegistryError("worker entry is invalid")
        if not isinstance(state, str) or not state:
            raise RegistryError("worker entry is invalid")
        return cls(
            worker_id, branch, Path(worktree), work_package_id,
            tuple(allowed_paths), state, worker_commit,
        )


@dataclass(frozen=True)
class WorktreeRegistry:
    team_id: str
    base_commit: str
    repository_root: Path
    integration_branch: str
    integration_worktree: Path
    workers: tuple[WorkerEntry, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "team_id": self.team_id,
            "base_commit": self.base_commit,
            "repository_root": str(self.repository_root),
            "integration_branch": self.integration_branch,
            "integration_worktree": str(self.integration_worktree),
            "workers": [worker.to_dict() for worker in self.workers],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorktreeRegistry":
        expected = {
            "team_id", "base_commit", "repository_root",
            "integration_branch", "integration_worktree", "workers",
        }
        if set(value) != expected:
            raise RegistryError("worktree registry has unexpected fields")
        team_id, base_commit, repository_root, integration_branch, integration_worktree, workers = (
            value["team_id"], value["base_commit"], value["repository_root"],
            value["integration_branch"], value["integration_worktree"], value["workers"],
        )
        if not isinstance(team_id, str) or not team_id:
            raise RegistryError("worktree registry is invalid")
        if not isinstance(base_commit, str) or not base_commit:
            raise RegistryError("worktree registry is invalid")
        if not isinstance(repository_root, str):
            raise RegistryError("worktree registry is invalid")
        if not isinstance(integration_branch, str) or not integration_branch:
            raise RegistryError("worktree registry is invalid")
        if not isinstance(integration_worktree, str):
            raise RegistryError("worktree registry is invalid")
        if not isinstance(workers, list):
            raise RegistryError("worktree registry is invalid")
        return cls(
            team_id, base_commit, Path(repository_root), integration_branch,
            Path(integration_worktree),
            tuple(WorkerEntry.from_dict(entry) for entry in workers),
        )

    def write(self, path: Path) -> None:
        _atomic_write(path, self.to_dict())

    @classmethod
    def read(cls, path: Path) -> "WorktreeRegistry":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RegistryError("worktree registry must be an object")
        return cls.from_dict(value)


@dataclass(frozen=True)
class MergePlan:
    order: tuple[str, ...]
    merged: tuple[str, ...]
    conflict: bool
    current: str | None = None
    integration_head: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "order": list(self.order),
            "current": self.current,
            "merged": list(self.merged),
            "conflict": self.conflict,
            "integration_head": self.integration_head,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "MergePlan":
        expected = {"order", "current", "merged", "conflict", "integration_head"}
        if set(value) != expected:
            raise RegistryError("merge plan has unexpected fields")
        order, current, merged, conflict, integration_head = (
            value["order"], value["current"], value["merged"],
            value["conflict"], value["integration_head"],
        )
        if not isinstance(order, list) or not all(isinstance(item, str) for item in order):
            raise RegistryError("merge plan is invalid")
        if current is not None and not isinstance(current, str):
            raise RegistryError("merge plan is invalid")
        if not isinstance(merged, list) or not all(isinstance(item, str) for item in merged):
            raise RegistryError("merge plan is invalid")
        if not isinstance(conflict, bool):
            raise RegistryError("merge plan is invalid")
        if integration_head is not None and not isinstance(integration_head, str):
            raise RegistryError("merge plan is invalid")
        return cls(tuple(order), tuple(merged), conflict, current, integration_head)

    def write(self, path: Path) -> None:
        _atomic_write(path, self.to_dict())

    @classmethod
    def read(cls, path: Path) -> "MergePlan":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RegistryError("merge plan must be an object")
        return cls.from_dict(value)
