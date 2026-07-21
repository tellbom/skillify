"""Pure, read-only reconciliation of a team's git-worktree/merge state on restart.

``diagnose()`` compares a persisted ``WorktreeRegistry`` (plus, best-effort, a
``MergePlan``) against live git state via ``WorktreeManager.inspect()`` and a
filesystem check for interrupted merges/cherry-picks. It never deletes or
modifies anything -- worktrees, branches, and the registry file itself are
left untouched regardless of what is found. The result is a diagnosis meant
to be written to ``recovery-state.json`` for operator/future-stage
visibility; it does not itself decide what ``ProviderRecovery`` status a
caller should return -- that mapping is ``ShogunProvider.recover()``'s job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from skillify.agent.shogun.registry import MergePlan, RegistryError, WorktreeRegistry
from skillify.agent.shogun.worktree import WorktreeManager, WorktreeManagerError

_INTERRUPT_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD")


@dataclass(frozen=True)
class RecoveryDiagnosis:
    """Reconciliation result for a team's git-worktree state, independent of
    tmux/process liveness. Written to recovery-state.json for operator/future-
    stage visibility; does NOT itself decide the ProviderRecovery status
    returned to callers -- that mapping happens in ShogunProvider.recover().
    """

    status: str  # "live" | "merge-interrupted" | "corrupt"
    detail: str  # human-readable explanation
    interrupted_worktrees: tuple[str, ...] = ()  # names with MERGE_HEAD/CHERRY_PICK_HEAD present


def _worktree_git_dir_name(repository_root: Path, worktree: Path) -> str | None:
    """Return the ``.git/worktrees/<name>`` directory that corresponds to
    ``worktree``, or ``None`` if no such directory exists."""
    worktrees_root = repository_root / ".git" / "worktrees"
    if not worktrees_root.is_dir():
        return None
    resolved = worktree.resolve() if worktree.exists() else worktree
    for candidate in worktrees_root.iterdir():
        gitdir_file = candidate / "gitdir"
        try:
            recorded = gitdir_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        # `gitdir` holds the path to the worktree's `.git` file, one level
        # below the worktree root itself.
        recorded_worktree = Path(recorded).parent
        try:
            recorded_worktree = recorded_worktree.resolve()
        except OSError:
            pass
        if recorded_worktree == resolved:
            return candidate.name
    return None


def _has_interrupt_marker(repository_root: Path, git_dir_name: str) -> bool:
    worktree_git_dir = repository_root / ".git" / "worktrees" / git_dir_name
    return any((worktree_git_dir / marker).exists() for marker in _INTERRUPT_MARKERS)


def diagnose(
    repository_root: Path,
    registry_path: Path,
    merge_plan_path: Path | None,
    worktree_manager: WorktreeManager,
) -> RecoveryDiagnosis:
    """Reconcile worktree-registry.json + merge-plan.json against live git state.

    Returns "corrupt" if registry_path is unreadable/invalid, or
    WorktreeManager.inspect() reports ok=False. Returns "merge-interrupted"
    if any worktree listed in the registry has a MERGE_HEAD or
    CHERRY_PICK_HEAD file under `.git/worktrees/<name>/`. Otherwise "live".
    Never deletes or modifies anything -- read-only reconciliation.
    """
    try:
        registry = WorktreeRegistry.read(registry_path)
    except (OSError, ValueError, RegistryError, json.JSONDecodeError) as exc:
        return RecoveryDiagnosis(
            status="corrupt", detail=f"worktree registry is unreadable/invalid: {exc}",
        )

    try:
        report = worktree_manager.inspect(registry)
    except WorktreeManagerError as exc:
        return RecoveryDiagnosis(
            status="corrupt", detail=f"failed to inspect live git worktree state: {exc}",
        )

    if not report.ok:
        details = []
        if report.missing_worktrees:
            details.append(f"missing_worktrees={[str(p) for p in report.missing_worktrees]}")
        if report.unexpected_branch:
            details.append(
                f"unexpected_branch={[(str(p), b) for p, b in report.unexpected_branch]}"
            )
        return RecoveryDiagnosis(
            status="corrupt", detail="worktree registry inconsistent with live git state: "
            + "; ".join(details),
        )

    # Optional, best-effort: a corrupt merge plan does not itself make the
    # team state "corrupt" -- only registry/live-git inconsistency does, per
    # the recovery-state design. It is only used to enrich diagnostic detail.
    merge_plan_note = ""
    if merge_plan_path is not None and merge_plan_path.exists():
        try:
            MergePlan.read(merge_plan_path)
        except (OSError, ValueError, RegistryError, json.JSONDecodeError):
            merge_plan_note = " (merge plan file present but unreadable)"

    all_worktrees = [
        ("integration", registry.integration_worktree),
        *((worker.worker_id, worker.worktree) for worker in registry.workers),
    ]
    interrupted: list[str] = []
    for name, worktree in all_worktrees:
        git_dir_name = _worktree_git_dir_name(repository_root, worktree)
        if git_dir_name is not None and _has_interrupt_marker(repository_root, git_dir_name):
            interrupted.append(name)

    if interrupted:
        return RecoveryDiagnosis(
            status="merge-interrupted",
            detail=f"worktrees with an in-progress merge/cherry-pick: {interrupted}"
            + merge_plan_note,
            interrupted_worktrees=tuple(interrupted),
        )

    return RecoveryDiagnosis(
        status="live", detail="registry matches live git state" + merge_plan_note,
    )
