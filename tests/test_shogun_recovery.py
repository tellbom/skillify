from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from skillify.agent.shogun.registry import WorktreeRegistry
from skillify.agent.shogun.team_recovery import RecoveryDiagnosis, diagnose
from skillify.agent.shogun.worktree import WorkerSpec, WorktreeManager

if os.name != "posix":
    pytest.skip("Shogun provider is Linux-only", allow_module_level=True)

from skillify.agent.provider import ProviderRecovery
from skillify.agent.providers import shogun as shogun_module
from skillify.agent.providers.shogun import ShogunProvider
from skillify.agent.shogun.fake_runtime import FakeRuntime
from skillify.agent.shogun.lifecycle import TeamHandle


def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(["init"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=repo)
    _git(["commit", "-m", "initial"], cwd=repo)
    return _git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()


def _make_registry(tmp_path: Path, *, worker_count: int = 1) -> tuple[Path, WorktreeRegistry, WorktreeManager]:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()
    workers = [
        WorkerSpec(f"worker-{i}", f"wp-{i}", ()) for i in range(1, worker_count + 1)
    ]
    registry = manager.create(
        repository_root=repo, base_commit=base_commit, team_id="team-1",
        workers=workers, state_root=state_root,
    )
    return repo, registry, manager


# ---------------------------------------------------------------------------
# diagnose()
# ---------------------------------------------------------------------------


def test_diagnose_reports_live_when_registry_matches_live_state(tmp_path: Path) -> None:
    repo, registry, manager = _make_registry(tmp_path)
    registry_path = tmp_path / "metadata" / "worktree-registry.json"
    registry.write(registry_path)

    diagnosis = diagnose(repo, registry_path, None, manager)

    assert diagnosis == RecoveryDiagnosis(
        status="live", detail="registry matches live git state",
    )


def test_diagnose_reports_corrupt_when_worktree_missing(tmp_path: Path) -> None:
    repo, registry, manager = _make_registry(tmp_path)
    registry_path = tmp_path / "metadata" / "worktree-registry.json"
    registry.write(registry_path)

    # Simulate drift: remove a worktree registered in the registry via plain
    # git, so WorktreeManager.inspect() reports ok=False.
    _git(["worktree", "remove", "--force", str(registry.workers[0].worktree)], cwd=repo)

    diagnosis = diagnose(repo, registry_path, None, manager)

    assert diagnosis.status == "corrupt"
    assert "missing_worktrees" in diagnosis.detail
    assert diagnosis.interrupted_worktrees == ()


def test_diagnose_reports_merge_interrupted_when_merge_head_present(tmp_path: Path) -> None:
    repo, registry, manager = _make_registry(tmp_path, worker_count=0)
    registry_path = tmp_path / "metadata" / "worktree-registry.json"
    registry.write(registry_path)

    integration = registry.integration_worktree
    _git(["checkout", "-b", "feature-a"], cwd=integration)
    (integration / "README.md").write_text("line-a\n", encoding="utf-8")
    _git(["commit", "-am", "a"], cwd=integration)
    _git(["checkout", registry.integration_branch], cwd=integration)
    (integration / "README.md").write_text("line-b\n", encoding="utf-8")
    _git(["commit", "-am", "b"], cwd=integration)
    # A real merge conflict, left un-aborted so MERGE_HEAD stays on disk.
    merge = subprocess.run(
        ["git", "merge", "feature-a", "--no-edit"],
        cwd=str(integration), capture_output=True, text=True, check=False,
    )
    assert merge.returncode != 0

    diagnosis = diagnose(repo, registry_path, None, manager)

    assert diagnosis.status == "merge-interrupted"
    assert diagnosis.interrupted_worktrees == ("integration",)


def test_diagnose_reports_corrupt_on_unparseable_registry_without_raising(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    manager = WorktreeManager()
    registry_path = tmp_path / "metadata" / "worktree-registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("not valid json {{{", encoding="utf-8")

    diagnosis = diagnose(repo, registry_path, None, manager)

    assert diagnosis.status == "corrupt"
    assert diagnosis.detail


# ---------------------------------------------------------------------------
# ShogunProvider.recover()
# ---------------------------------------------------------------------------


def _write_team_handle(run_dir: Path, *, session: str = "shogun") -> None:
    TeamHandle(session, run_dir).write(run_dir / "team-handle.json")


def _write_provider_state(run_dir: Path, *, task_id: str) -> None:
    state_path = run_dir / "provider-state.json"
    state_path.write_text(json.dumps({
        "handle_id": "handle-1", "task_id": task_id, "session_id": "session-1",
    }), encoding="utf-8")


def _write_settings(run_dir: Path) -> None:
    settings_path = run_dir / "config" / "settings.yaml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("skillify:\n  credential_refs: {}\n", encoding="utf-8")


def _provider(tmp_path: Path, runtime: FakeRuntime) -> ShogunProvider:
    return ShogunProvider(
        manifest_path=tmp_path / "manifest.json",
        artifact_path=tmp_path / "bundle.tar.gz",
        install_root=tmp_path / "install",
        cache_root=tmp_path / "cache",
        runtime=runtime,
    )


def test_recover_without_worktree_registry_is_unchanged(tmp_path: Path) -> None:
    """Regression: teams that never used the git-worktree feature must see
    identical recover() behavior to before this feature existed."""
    runtime = FakeRuntime()
    runtime.alive = True
    provider = _provider(tmp_path, runtime)
    task_id = "task-1"
    run_dir = (provider.cache_root / task_id).resolve()
    _write_team_handle(run_dir)
    _write_provider_state(run_dir, task_id=task_id)
    _write_settings(run_dir)

    recovery = provider.recover(task_id)

    assert recovery.status == "live"
    assert not (run_dir / "recovery-state.json").exists()


def test_recover_without_worktree_registry_dead_path_is_unchanged(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    runtime.alive = False
    provider = _provider(tmp_path, runtime)
    task_id = "task-1"
    run_dir = (provider.cache_root / task_id).resolve()
    _write_team_handle(run_dir)
    _write_provider_state(run_dir, task_id=task_id)

    recovery = provider.recover(task_id)

    assert recovery == ProviderRecovery("dead")
    assert not (run_dir / "recovery-state.json").exists()


def test_recover_forces_dead_when_worktree_state_is_corrupt_even_if_alive(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    runtime.alive = True
    provider = _provider(tmp_path, runtime)
    task_id = "task-1"
    run_dir = (provider.cache_root / task_id).resolve()
    _write_team_handle(run_dir)
    _write_provider_state(run_dir, task_id=task_id)
    _write_settings(run_dir)

    (run_dir / "worktree-registry.json").parent.mkdir(parents=True, exist_ok=True)
    (run_dir / "worktree-registry.json").write_text("not valid json {{{", encoding="utf-8")

    recovery = provider.recover(task_id)

    assert recovery == ProviderRecovery("dead")
    # run_dir itself must survive (not be rmtree'd) so the registry and the
    # recovery-state.json just written remain on disk for forensics -- per
    # the brief's binding decision to never delete worktree/branch/registry
    # evidence when state is diagnosed as corrupt.
    assert run_dir.exists()
    recovery_state_path = run_dir / "recovery-state.json"
    assert recovery_state_path.exists()
    payload = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert payload["status"] == "corrupt"


def test_recover_writes_live_recovery_state_when_worktree_registry_consistent(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    runtime.alive = True
    provider = _provider(tmp_path, runtime)
    task_id = "task-1"
    run_dir = (provider.cache_root / task_id).resolve()
    _write_team_handle(run_dir)
    _write_provider_state(run_dir, task_id=task_id)
    _write_settings(run_dir)

    repo, registry, _manager = _make_registry(tmp_path)
    registry.write(run_dir / "worktree-registry.json")

    recovery = provider.recover(task_id)

    assert recovery.status == "live"
    payload = json.loads((run_dir / "recovery-state.json").read_text(encoding="utf-8"))
    assert payload["status"] == "live"
