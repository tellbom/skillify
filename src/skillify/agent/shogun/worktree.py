"""Deterministic create/inspect/cleanup of real git worktrees for a Shogun team.

``WorktreeManager`` is a pure utility around ``git worktree`` subprocess calls.
It does not run background threads or daemons, does not touch the launcher or
pane integration, and does not implement scope-gate or merge logic — those
are later stages. Its only job is: for a given team, create one integration
worktree plus one worktree per worker (all branched from the exact same
frozen ``base_commit``), record the result as a ``WorktreeRegistry``
(``registry.py``, stage S1), reconcile that registry against live
``git worktree list`` state, and tear worktrees down safely.

Safety model for cleanup: every worktree this class creates gets an owner
marker file (``.skillify-team-owner``) at its root containing the team id and
a normalized repository identity. Before deleting anything, cleanup verifies
three independent things — the marker's team_id matches, the marker's
repository identity matches, and the target path resolves to somewhere under
``<state_root>/teams/`` — and refuses (raising, without deleting) if any of
them fail. Deletion itself is always via ``git worktree remove`` (falling
back to ``--force`` only if a clean remove is rejected) plus ``git worktree
prune`` plus ``git branch -D``; this class never calls ``shutil.rmtree`` or
otherwise recursively deletes a directory, so it is structurally impossible
for cleanup to behave like ``rm -rf`` on an arbitrary path.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from skillify.agent.shogun.registry import WorkerEntry, WorktreeRegistry

_OWNER_MARKER_NAME = ".skillify-team-owner"


class WorktreeManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerSpec:
    """Input to :meth:`WorktreeManager.create` describing one worker to provision."""

    worker_id: str
    work_package_id: str
    allowed_paths: tuple[str, ...]


@dataclass(frozen=True)
class InspectionReport:
    """Result of reconciling a :class:`WorktreeRegistry` against live git state."""

    ok: bool
    missing_worktrees: tuple[Path, ...]
    unexpected_branch: tuple[tuple[Path, str], ...]


def _run_git(args: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise WorktreeManagerError(
            f"git {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result


def _repository_identity(repository_root: Path) -> str:
    """A stable identifier for the repository, independent of worktree path.

    Uses the root commit hash when available (identical across all worktrees
    of the same repo, unlike an ordinary path string), falling back to the
    resolved repository path for a repository with no commits yet.
    """
    result = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=str(repository_root), capture_output=True, text=True, check=False,
    )
    roots = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode == 0 and roots:
        return roots[0]
    return str(repository_root.resolve())


def _team_root(state_root: Path, team_id: str) -> Path:
    return state_root / "teams" / team_id


def _worktree_path(state_root: Path, team_id: str, name: str) -> Path:
    return _team_root(state_root, team_id) / "worktrees" / name


def _branch_name(team_id: str, *, worker_id: str | None) -> str:
    if worker_id is None:
        return f"skillify/team/{team_id}/integration"
    return f"skillify/team/{team_id}/worker/{worker_id}"


def _write_owner_marker(worktree: Path, *, team_id: str, repository_identity: str) -> None:
    marker = {"team_id": team_id, "repository_root": repository_identity}
    (worktree / _OWNER_MARKER_NAME).write_text(
        json.dumps(marker, sort_keys=True), encoding="utf-8",
    )


def _read_owner_marker(worktree: Path) -> dict[str, object] | None:
    marker_path = worktree / _OWNER_MARKER_NAME
    if not marker_path.is_file():
        return None
    try:
        value = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    return value


class WorktreeManager:
    """Creates, inspects, and cleans up the git worktrees for one Shogun team."""

    def create(
        self,
        *,
        repository_root: Path,
        base_commit: str,
        team_id: str,
        workers: Sequence[WorkerSpec],
        state_root: Path,
    ) -> WorktreeRegistry:
        """Create one integration worktree plus one worktree per worker.

        All branches are created with ``git worktree add <path> -b <branch>
        <base_commit>`` — an explicit start-point argument, so every branch is
        guaranteed to be cut from the exact same commit rather than from
        whatever HEAD happens to be at call time. Raises
        ``WorktreeManagerError`` (without leaving partially created state
        registered) if any branch name is already taken or any git
        invocation fails; worktrees already created during this call are
        rolled back on failure.
        """
        repository_root = repository_root.resolve()
        state_root = state_root.resolve()
        repository_identity = _repository_identity(repository_root)

        # Enable per-worktree local config (extensions.worktreeConfig) so each
        # worker's `git config --worktree user.name/email` (set by the pane
        # launcher) is genuinely isolated. Without this, `git config --local`
        # writes to the single config file shared by the main repo and every
        # worktree, so worker identities silently collide under concurrent
        # pane launches (confirmed via real concurrent Worker panes in S10
        # real-machine testing: both workers ended up with the same,
        # last-writer-wins user.name). Idempotent -- safe to set every call.
        _run_git(["config", "extensions.worktreeConfig", "true"], cwd=repository_root)

        worker_ids = [worker.worker_id for worker in workers]
        if len(worker_ids) != len(set(worker_ids)):
            raise WorktreeManagerError("duplicate worker_id in workers")

        created_paths: list[Path] = []
        created_branches: list[str] = []
        try:
            integration_path = _worktree_path(state_root, team_id, "integration")
            integration_branch = _branch_name(team_id, worker_id=None)
            self._add_worktree(
                repository_root, integration_path, integration_branch, base_commit,
            )
            created_paths.append(integration_path)
            created_branches.append(integration_branch)
            _write_owner_marker(
                integration_path, team_id=team_id, repository_identity=repository_identity,
            )

            worker_entries = []
            for worker in workers:
                worktree_path = _worktree_path(state_root, team_id, worker.worker_id)
                branch = _branch_name(team_id, worker_id=worker.worker_id)
                self._add_worktree(repository_root, worktree_path, branch, base_commit)
                created_paths.append(worktree_path)
                created_branches.append(branch)
                _write_owner_marker(
                    worktree_path, team_id=team_id, repository_identity=repository_identity,
                )
                worker_entries.append(
                    WorkerEntry(
                        worker_id=worker.worker_id,
                        branch=branch,
                        worktree=worktree_path,
                        work_package_id=worker.work_package_id,
                        allowed_paths=tuple(worker.allowed_paths),
                        state="assigned",
                        worker_commit=None,
                    )
                )
        except Exception:
            self._rollback(repository_root, created_paths, created_branches)
            raise

        return WorktreeRegistry(
            team_id=team_id,
            base_commit=base_commit,
            repository_root=repository_root,
            integration_branch=integration_branch,
            integration_worktree=integration_path,
            workers=tuple(worker_entries),
        )

    def _add_worktree(
        self, repository_root: Path, worktree_path: Path, branch: str, base_commit: str,
    ) -> None:
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            ["worktree", "add", str(worktree_path), "-b", branch, base_commit],
            cwd=repository_root,
        )

    def _rollback(
        self, repository_root: Path, paths: list[Path], branches: list[str],
    ) -> None:
        for path in reversed(paths):
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=str(repository_root), capture_output=True, text=True, check=False,
            )
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(repository_root), capture_output=True, text=True, check=False,
        )
        for branch in reversed(branches):
            subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=str(repository_root), capture_output=True, text=True, check=False,
            )

    def inspect(self, registry: WorktreeRegistry) -> InspectionReport:
        """Reconcile a registry against live ``git worktree list --porcelain`` state."""
        live = self._live_worktrees(registry.repository_root)

        expected: list[tuple[Path, str]] = [
            (registry.integration_worktree.resolve(), registry.integration_branch),
        ]
        expected.extend(
            (worker.worktree.resolve(), worker.branch) for worker in registry.workers
        )

        missing: list[Path] = []
        unexpected_branch: list[tuple[Path, str]] = []
        for path, expected_branch in expected:
            actual_branch = live.get(path)
            if actual_branch is None:
                missing.append(path)
            elif actual_branch != expected_branch:
                unexpected_branch.append((path, actual_branch))

        ok = not missing and not unexpected_branch
        return InspectionReport(
            ok=ok,
            missing_worktrees=tuple(missing),
            unexpected_branch=tuple(unexpected_branch),
        )

    def _live_worktrees(self, repository_root: Path) -> dict[Path, str]:
        result = _run_git(["worktree", "list", "--porcelain"], cwd=repository_root)
        worktrees: dict[Path, str] = {}
        current_path: Path | None = None
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                current_path = Path(line[len("worktree "):]).resolve()
            elif line.startswith("branch ") and current_path is not None:
                ref = line[len("branch "):]
                branch = ref.removeprefix("refs/heads/")
                worktrees[current_path] = branch
        return worktrees

    def cleanup(self, registry: WorktreeRegistry, *, state_root: Path) -> None:
        """Remove every worktree and branch in ``registry``.

        Before deleting anything, every worktree path is checked against
        three conditions: its owner marker's ``team_id`` matches
        ``registry.team_id``, its owner marker's repository identity matches
        the repository's, and the path resolves to somewhere under
        ``<state_root>/teams/``. If any worktree fails any check, cleanup
        refuses and raises ``WorktreeManagerError`` without deleting
        anything (for that worktree or any other passed to this call).
        Deletion itself is only ever ``git worktree remove``, ``git worktree
        prune``, and ``git branch -D`` — never a recursive filesystem delete.
        """
        state_root = state_root.resolve()
        repository_root = registry.repository_root.resolve()
        repository_identity = _repository_identity(repository_root)
        team_root = _team_root(state_root, registry.team_id).resolve()

        targets: list[tuple[Path, str]] = [
            (registry.integration_worktree, registry.integration_branch),
        ]
        targets.extend((worker.worktree, worker.branch) for worker in registry.workers)

        for path, _branch in targets:
            self._verify_safe_to_delete(
                path,
                team_id=registry.team_id,
                repository_identity=repository_identity,
                team_root=team_root,
            )

        for path, branch in targets:
            self._remove_worktree(repository_root, path)
            self._delete_branch(repository_root, branch)

        _run_git(["worktree", "prune"], cwd=repository_root)

    def _verify_safe_to_delete(
        self, path: Path, *, team_id: str, repository_identity: str, team_root: Path,
    ) -> None:
        resolved = path.resolve() if path.exists() else path
        try:
            resolved.relative_to(team_root)
        except ValueError as exc:
            raise WorktreeManagerError(
                f"refusing to clean up {resolved}: not located under {team_root}"
            ) from exc

        marker = _read_owner_marker(path)
        if marker is None:
            raise WorktreeManagerError(
                f"refusing to clean up {resolved}: missing owner marker"
            )
        if marker.get("team_id") != team_id:
            raise WorktreeManagerError(
                f"refusing to clean up {resolved}: owner marker team_id mismatch"
            )
        if marker.get("repository_root") != repository_identity:
            raise WorktreeManagerError(
                f"refusing to clean up {resolved}: owner marker repository mismatch"
            )

    def _remove_worktree(self, repository_root: Path, path: Path) -> None:
        result = subprocess.run(
            ["git", "worktree", "remove", str(path)],
            cwd=str(repository_root), capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            return
        forced = subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            cwd=str(repository_root), capture_output=True, text=True, check=False,
        )
        if forced.returncode != 0:
            raise WorktreeManagerError(
                f"git worktree remove failed for {path}: {forced.stderr.strip()}"
            )

    def _delete_branch(self, repository_root: Path, branch: str) -> None:
        subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=str(repository_root), capture_output=True, text=True, check=False,
        )
