from __future__ import annotations

from pathlib import Path

import pytest

from skillify.agent.shogun.lifecycle import TeamHandle
from skillify.agent.shogun.registry import (
    MergePlan,
    RegistryError,
    WorkerEntry,
    WorktreeRegistry,
)


def _registry(tmp_path: Path) -> WorktreeRegistry:
    return WorktreeRegistry(
        team_id="team-1",
        base_commit="abc123",
        repository_root=tmp_path / "repo",
        integration_branch="skillify/team/team-1/integration",
        integration_worktree=tmp_path / "worktrees/integration",
        workers=(
            WorkerEntry(
                worker_id="worker-1",
                branch="skillify/team/team-1/worker/worker-1",
                worktree=tmp_path / "worktrees/worker-1",
                work_package_id="wp-1",
                allowed_paths=("src/a.py", "src/b.py"),
                state="assigned",
                worker_commit=None,
            ),
            WorkerEntry(
                worker_id="worker-2",
                branch="skillify/team/team-1/worker/worker-2",
                worktree=tmp_path / "worktrees/worker-2",
                work_package_id="wp-2",
                allowed_paths=("src/c.py",),
                state="committed",
                worker_commit="def456",
            ),
        ),
    )


def test_worktree_registry_roundtrips(tmp_path: Path) -> None:
    original = _registry(tmp_path)
    path = tmp_path / "metadata/worktree-registry.json"

    original.write(path)

    assert WorktreeRegistry.read(path) == original


def test_worktree_registry_write_is_atomic(tmp_path: Path) -> None:
    original = _registry(tmp_path)
    path = tmp_path / "metadata/worktree-registry.json"

    original.write(path)

    assert not path.with_suffix(path.suffix + ".tmp").exists()
    assert path.exists()


def test_worktree_registry_rejects_unexpected_fields(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        WorktreeRegistry.from_dict(
            {**_registry(tmp_path).to_dict(), "unexpected": "field"},
        )


def _merge_plan() -> MergePlan:
    return MergePlan(
        order=("worker-1", "worker-2"),
        current="worker-1",
        merged=(),
        conflict=False,
        integration_head="abc123",
    )


def test_merge_plan_roundtrips(tmp_path: Path) -> None:
    original = _merge_plan()
    path = tmp_path / "metadata/merge-plan.json"

    original.write(path)

    assert MergePlan.read(path) == original


def test_merge_plan_roundtrips_with_none_fields(tmp_path: Path) -> None:
    original = MergePlan(
        order=("worker-1",), current=None, merged=(), conflict=False, integration_head=None,
    )
    path = tmp_path / "metadata/merge-plan.json"

    original.write(path)

    assert MergePlan.read(path) == original


def test_merge_plan_write_is_atomic(tmp_path: Path) -> None:
    original = _merge_plan()
    path = tmp_path / "metadata/merge-plan.json"

    original.write(path)

    assert not path.with_suffix(path.suffix + ".tmp").exists()
    assert path.exists()


def test_merge_plan_rejects_unexpected_fields(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        MergePlan.from_dict({**_merge_plan().to_dict(), "unexpected": "field"})


def test_old_format_team_handle_still_reads(tmp_path: Path) -> None:
    path = tmp_path / "team-handle.json"
    path.write_text(
        '{"session": "shogun", "run_dir": "%s"}' % str((tmp_path / "run").resolve()).replace("\\", "\\\\"),
        encoding="utf-8",
    )

    handle = TeamHandle.read(path)

    assert handle.session == "shogun"
    assert handle.run_dir == (tmp_path / "run").resolve()
    assert handle.team_id is None
    assert handle.base_commit is None


def test_team_handle_roundtrips_with_new_optional_fields(tmp_path: Path) -> None:
    original = TeamHandle(
        "shogun", (tmp_path / "run").resolve(), team_id="team-1", base_commit="abc123",
    )
    path = tmp_path / "team-handle.json"

    original.write(path)

    assert TeamHandle.read(path) == original
