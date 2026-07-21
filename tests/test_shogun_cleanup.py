"""S9: worktree/branch cleanup wired into ShogunLifecycle.cancel()/stop().

Uses real temporary git repositories and real WorktreeRegistry/WorktreeManager
(no mocked git), following the same fixture conventions as
tests/test_shogun_worktree.py and tests/test_shogun_lifecycle.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from skillify.agent.shogun.config_gen import GeneratedShogunConfig
from skillify.agent.shogun.fake_runtime import FakeRuntime
from skillify.agent.shogun.lifecycle import ShogunLifecycle
from skillify.agent.shogun.worktree import WorkerSpec, WorktreeManager


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


def _live_worktree_paths(repo: Path) -> set[Path]:
    result = _git(["worktree", "list", "--porcelain"], cwd=repo)
    paths = set()
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.add(Path(line[len("worktree "):]).resolve())
    return paths


def _generated(run_dir: Path) -> GeneratedShogunConfig:
    queue = run_dir / "queue"
    queue.mkdir(parents=True)
    return GeneratedShogunConfig(
        run_dir / "config/settings.yaml", run_dir / "config/permissions.yaml",
        queue, (str(run_dir / "shutsujin_departure.sh"),), {},
    )


def test_cancel_cleans_up_worktrees_and_removes_run_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    run_dir = tmp_path / "run"
    registry = manager.create(
        repository_root=repo, base_commit=base_commit, team_id="team-1",
        workers=[WorkerSpec("worker-1", "wp-1", ())], state_root=state_root,
    )
    generated = _generated(run_dir)
    registry.write(run_dir / "worktree-registry.json")

    runtime = FakeRuntime()
    guard = tmp_path / "active-team.lock"
    lifecycle = ShogunLifecycle(runtime, guard)
    team = lifecycle.start("task-1", generated, install_root=tmp_path)

    lifecycle.cancel(team)

    # Worktrees/branches are gone.
    live = _live_worktree_paths(repo)
    assert live == {repo.resolve()}
    branches = _git(["branch", "--list"], cwd=repo).stdout
    assert "skillify/team/team-1/integration" not in branches
    assert "skillify/team/team-1/worker/worker-1" not in branches

    # run_dir and guard are both gone -- normal cancel/stop behavior preserved.
    assert not run_dir.exists()
    assert not guard.exists()


def test_cancel_without_registry_behaves_like_before(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    guard = tmp_path / "active-team.lock"
    lifecycle = ShogunLifecycle(runtime, guard)
    run_dir = tmp_path / "run"
    team = lifecycle.start("task-1", _generated(run_dir), install_root=tmp_path)

    lifecycle.cancel(team)

    assert not run_dir.exists()
    assert not guard.exists()
    assert not runtime.is_alive(team.handle)


def test_cancel_preserves_run_dir_when_cleanup_refuses_but_still_releases_guard(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    run_dir = tmp_path / "run"
    registry = manager.create(
        repository_root=repo, base_commit=base_commit, team_id="team-1",
        workers=[], state_root=state_root,
    )
    generated = _generated(run_dir)
    registry.write(run_dir / "worktree-registry.json")

    # Tamper with the owner marker so WorktreeManager.cleanup() refuses,
    # reusing the same technique as test_shogun_worktree.py's
    # test_cleanup_refuses_when_owner_marker_team_id_mismatches.
    marker_path = registry.integration_worktree / ".skillify-team-owner"
    marker_path.write_text(
        '{"team_id": "some-other-team", "repository_root": "irrelevant"}', encoding="utf-8",
    )

    runtime = FakeRuntime()
    guard = tmp_path / "active-team.lock"
    lifecycle = ShogunLifecycle(runtime, guard)
    team = lifecycle.start("task-1", generated, install_root=tmp_path)

    lifecycle.cancel(team)

    # run_dir (forensics: registry, merge-plan, etc.) is preserved.
    assert run_dir.exists()
    assert (run_dir / "worktree-registry.json").exists()
    # Guard is still released so future team starts are not blocked forever.
    assert not guard.exists()
    # Process termination still ran normally.
    assert ("kill-session", team.handle.session) in runtime.actions
    assert not runtime.is_alive(team.handle)
    # active team pointer still cleared.
    assert lifecycle.active is None

    # The worktree itself was never deleted since cleanup refused.
    live = _live_worktree_paths(repo)
    assert registry.integration_worktree.resolve() in live


def test_stop_preserves_run_dir_when_state_root_derivation_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    run_dir = tmp_path / "run"
    registry = manager.create(
        repository_root=repo, base_commit=base_commit, team_id="team-1",
        workers=[], state_root=state_root,
    )
    generated = _generated(run_dir)

    # Rewrite the registry's integration_worktree so it no longer matches the
    # <state_root>/teams/<team_id>/worktrees/<name> convention -- simulating
    # a registry that state_root cannot be safely derived from.
    from dataclasses import replace

    broken_registry = replace(
        registry, integration_worktree=tmp_path / "somewhere" / "else",
    )
    broken_registry.write(run_dir / "worktree-registry.json")

    runtime = FakeRuntime()
    guard = tmp_path / "active-team.lock"
    lifecycle = ShogunLifecycle(runtime, guard)
    team = lifecycle.start("task-1", generated, install_root=tmp_path)

    lifecycle.stop(team)

    assert run_dir.exists()
    assert not guard.exists()
    assert not runtime.is_alive(team.handle)

    # The real worktree created earlier was never touched (cleanup never
    # even attempted the git calls since state_root derivation failed first).
    live = _live_worktree_paths(repo)
    assert registry.integration_worktree.resolve() in live
