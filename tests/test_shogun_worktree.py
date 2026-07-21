from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skillify.agent.shogun.registry import WorktreeRegistry
from skillify.agent.shogun.worktree import (
    WorktreeManager,
    WorktreeManagerError,
    WorkerSpec,
)


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
    result = _git(["rev-parse", "HEAD"], cwd=repo)
    return result.stdout.strip()


def _live_worktree_paths(repo: Path) -> set[Path]:
    result = _git(["worktree", "list", "--porcelain"], cwd=repo)
    paths = set()
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.add(Path(line[len("worktree "):]).resolve())
    return paths


def test_create_makes_independent_worktrees_and_branches_off_same_base(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    registry = manager.create(
        repository_root=repo,
        base_commit=base_commit,
        team_id="team-1",
        workers=[
            WorkerSpec("worker-1", "wp-1", ("src/a.py",)),
            WorkerSpec("worker-2", "wp-2", ("src/b.py",)),
        ],
        state_root=state_root,
    )

    assert registry.integration_worktree != registry.workers[0].worktree
    assert registry.workers[0].worktree != registry.workers[1].worktree
    assert registry.integration_branch == "skillify/team/team-1/integration"
    assert registry.workers[0].branch == "skillify/team/team-1/worker/worker-1"
    assert registry.workers[1].branch == "skillify/team/team-1/worker/worker-2"

    live = _live_worktree_paths(repo)
    assert registry.integration_worktree.resolve() in live
    assert registry.workers[0].worktree.resolve() in live
    assert registry.workers[1].worktree.resolve() in live

    for worktree in (registry.integration_worktree, *[w.worktree for w in registry.workers]):
        head = _git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()
        assert head == base_commit

    for worktree in (registry.integration_worktree, *[w.worktree for w in registry.workers]):
        assert (worktree / ".skillify-team-owner").is_file()


def test_create_enables_per_worktree_config_isolation(tmp_path: Path) -> None:
    """extensions.worktreeConfig must be enabled so `git config --worktree`
    (used by the pane launcher to set per-worker identity) is genuinely
    isolated instead of silently sharing the single config file every
    worktree of a repo shares by default (confirmed as a real bug via
    concurrent Worker panes in S10 real-machine testing: both workers ended
    up with the same, last-writer-wins user.name under `--local`)."""
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    registry = manager.create(
        repository_root=repo,
        base_commit=base_commit,
        team_id="team-1",
        workers=[WorkerSpec("worker-1", "wp-1", ("src/a.py",))],
        state_root=state_root,
    )

    result = subprocess.run(
        ["git", "config", "--get", "extensions.worktreeConfig"],
        cwd=str(repo), capture_output=True, text=True, check=False,
    )
    assert result.stdout.strip() == "true"

    # Per-worktree config must actually be independent between two worktrees.
    subprocess.run(
        ["git", "config", "--worktree", "user.name", "worker-1-identity"],
        cwd=str(registry.workers[0].worktree), check=True,
    )
    subprocess.run(
        ["git", "config", "--worktree", "user.name", "integration-identity"],
        cwd=str(registry.integration_worktree), check=True,
    )
    worker_name = subprocess.run(
        ["git", "config", "--worktree", "--get", "user.name"],
        cwd=str(registry.workers[0].worktree), capture_output=True, text=True, check=True,
    ).stdout.strip()
    integration_name = subprocess.run(
        ["git", "config", "--worktree", "--get", "user.name"],
        cwd=str(registry.integration_worktree), capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert worker_name == "worker-1-identity"
    assert integration_name == "integration-identity"


def test_create_writes_owner_marker_with_team_id_and_repo_identity(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    registry = manager.create(
        repository_root=repo, base_commit=base_commit, team_id="team-1",
        workers=[], state_root=state_root,
    )

    marker_path = registry.integration_worktree / ".skillify-team-owner"
    content = marker_path.read_text(encoding="utf-8")
    assert '"team_id": "team-1"' in content


def test_create_rejects_duplicate_worker_id(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    with pytest.raises(WorktreeManagerError):
        manager.create(
            repository_root=repo, base_commit=base_commit, team_id="team-1",
            workers=[
                WorkerSpec("worker-1", "wp-1", ()),
                WorkerSpec("worker-1", "wp-2", ()),
            ],
            state_root=state_root,
        )


def test_create_rejects_reused_branch_name_and_leaves_no_partial_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    # Pre-create a branch that collides with the integration branch name git
    # would otherwise pick, forcing "git worktree add -b" to fail on its own.
    _git(["branch", "skillify/team/team-1/integration"], cwd=repo)

    with pytest.raises(WorktreeManagerError):
        manager.create(
            repository_root=repo, base_commit=base_commit, team_id="team-1",
            workers=[WorkerSpec("worker-1", "wp-1", ())],
            state_root=state_root,
        )

    # No worktree should have been left registered in git's metadata as a
    # result of the failed create() call (only the main worktree remains).
    live = _live_worktree_paths(repo)
    assert live == {repo.resolve()}


def test_inspect_reports_ok_when_registry_matches_live_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    registry = manager.create(
        repository_root=repo, base_commit=base_commit, team_id="team-1",
        workers=[WorkerSpec("worker-1", "wp-1", ())], state_root=state_root,
    )

    report = manager.inspect(registry)

    assert report.ok is True
    assert report.missing_worktrees == ()
    assert report.unexpected_branch == ()


def test_inspect_reports_missing_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    registry = manager.create(
        repository_root=repo, base_commit=base_commit, team_id="team-1",
        workers=[WorkerSpec("worker-1", "wp-1", ())], state_root=state_root,
    )

    # Remove the worker worktree out from under the registry using plain git,
    # simulating drift between recorded state and live git state.
    _git(["worktree", "remove", "--force", str(registry.workers[0].worktree)], cwd=repo)

    report = manager.inspect(registry)

    assert report.ok is False
    assert registry.workers[0].worktree.resolve() in report.missing_worktrees


def test_cleanup_leaves_zero_residue(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    registry = manager.create(
        repository_root=repo, base_commit=base_commit, team_id="team-1",
        workers=[
            WorkerSpec("worker-1", "wp-1", ()),
            WorkerSpec("worker-2", "wp-2", ()),
        ],
        state_root=state_root,
    )

    manager.cleanup(registry, state_root=state_root)

    live = _live_worktree_paths(repo)
    assert live == {repo.resolve()}
    assert not (repo / ".git" / "worktrees").exists() or not list(
        (repo / ".git" / "worktrees").iterdir()
    )
    assert not registry.integration_worktree.exists()
    assert not registry.workers[0].worktree.exists()
    assert not registry.workers[1].worktree.exists()

    branches = _git(["branch", "--list"], cwd=repo).stdout
    assert "skillify/team/team-1/integration" not in branches
    assert "skillify/team/team-1/worker/worker-1" not in branches
    assert "skillify/team/team-1/worker/worker-2" not in branches


def test_cleanup_refuses_when_owner_marker_team_id_mismatches(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    registry = manager.create(
        repository_root=repo, base_commit=base_commit, team_id="team-1",
        workers=[WorkerSpec("worker-1", "wp-1", ())], state_root=state_root,
    )

    # Tamper with the owner marker so it claims a different team.
    marker_path = registry.integration_worktree / ".skillify-team-owner"
    marker_path.write_text(
        '{"team_id": "some-other-team", "repository_root": "irrelevant"}', encoding="utf-8",
    )

    with pytest.raises(WorktreeManagerError):
        manager.cleanup(registry, state_root=state_root)

    # Nothing should have been deleted: refusal must happen before any
    # git worktree remove / branch -D call for any target in this registry.
    live = _live_worktree_paths(repo)
    assert registry.integration_worktree.resolve() in live
    assert registry.workers[0].worktree.resolve() in live
    branches = _git(["branch", "--list"], cwd=repo).stdout
    assert "skillify/team/team-1/integration" in branches
    assert "skillify/team/team-1/worker/worker-1" in branches


def test_cleanup_refuses_when_owner_marker_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    registry = manager.create(
        repository_root=repo, base_commit=base_commit, team_id="team-1",
        workers=[], state_root=state_root,
    )

    (registry.integration_worktree / ".skillify-team-owner").unlink()

    with pytest.raises(WorktreeManagerError):
        manager.cleanup(registry, state_root=state_root)

    live = _live_worktree_paths(repo)
    assert registry.integration_worktree.resolve() in live


def test_cleanup_refuses_when_path_outside_state_root(tmp_path: Path) -> None:
    """A registry pointing at a worktree outside <state>/teams/ must be refused,
    even if it happens to carry a well-formed owner marker, since a corrupted
    or maliciously edited registry file must never be able to make cleanup
    delete an arbitrary path such as the user's main working tree."""
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    outside_target = tmp_path / "not-under-state-root"
    _git(
        ["worktree", "add", str(outside_target), "-b", "skillify/team/team-1/integration",
         base_commit],
        cwd=repo,
    )
    (outside_target / ".skillify-team-owner").write_text(
        '{"team_id": "team-1", "repository_root": "irrelevant"}', encoding="utf-8",
    )

    forged_registry = WorktreeRegistry(
        team_id="team-1",
        base_commit=base_commit,
        repository_root=repo,
        integration_branch="skillify/team/team-1/integration",
        integration_worktree=outside_target,
        workers=(),
    )

    with pytest.raises(WorktreeManagerError):
        manager.cleanup(forged_registry, state_root=state_root)

    live = _live_worktree_paths(repo)
    assert outside_target.resolve() in live


def test_cleanup_refuses_when_repository_identity_mismatches(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    base_commit = _init_repo(repo_a)
    repo_b = tmp_path / "repo-b"
    _init_repo(repo_b)
    state_root = tmp_path / "state"
    manager = WorktreeManager()

    registry = manager.create(
        repository_root=repo_a, base_commit=base_commit, team_id="team-1",
        workers=[], state_root=state_root,
    )

    # Point the registry's repository_root at a different repo, so the
    # identity computed for cleanup no longer matches the marker written
    # during create() against repo_a.
    forged_registry = WorktreeRegistry(
        team_id="team-1",
        base_commit=base_commit,
        repository_root=repo_b,
        integration_branch=registry.integration_branch,
        integration_worktree=registry.integration_worktree,
        workers=(),
    )

    with pytest.raises(WorktreeManagerError):
        manager.cleanup(forged_registry, state_root=state_root)

    live = _live_worktree_paths(repo_a)
    assert registry.integration_worktree.resolve() in live
