"""Deterministic git merge tool for the Shogun integration phase.

``IntegrationEngine`` is a stateless tool -- a collection of pure static
methods that accept all parameters explicitly. It does not schedule agents,
manage lifecycles, or run as a service. Callers (the existing integration pane
in a Shogun formation) invoke ``merge_worker`` for each worker in merge-plan
order.

Conflict handling: when a merge produces conflicts, the working tree is left
intact for manual resolution (no ``git merge --abort``). The caller is
responsible for resolving conflicts and re-invoking with the resolved state.
``-X ours`` / ``-X theirs`` override flags are forbidden at the caller level;
this engine never passes them to ``git merge``.

Verification commands: after a successful merge, each command in
``verification_commands`` is executed in sequence in the repository root.
Command failure is recorded but does not block integration commit generation.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from skillify.agent.shogun.registry import MergePlan


@dataclass(frozen=True)
class IntegrationResult:
    """The outcome of merging one worker into the integration branch.

    This is a plain data record. It contains no agent handles, no scheduling
    fields, and no lifecycle state -- only the merge outcome and verification
    results.
    """

    success: bool
    integration_commit: str | None
    conflict_files: tuple[str, ...]
    conflict_details: str | None
    verification_results: tuple[tuple[str, int, str, str], ...]
    merge_plan_updated: MergePlan


class IntegrationEngine:
    """Deterministic git merge tool for the Shogun integration phase.

    All methods are ``@staticmethod`` -- no instance state, no lifecycle, no
    agent scheduling. This class is a pure utility called by the existing
    integration pane in a Shogun formation.

    **Caller constraint**: never pass ``-X ours`` or ``-X theirs`` to
    ``git merge``. Conflicts must be resolved manually by the integration
    pane, not silently overridden.
    """

    @staticmethod
    def merge_worker(
        repository_root: Path,
        integration_branch: str,
        worker_branch: str,
        worker_id: str,
        merge_plan: MergePlan,
        merge_plan_path: Path | None = None,
        verification_commands: Sequence[str] = (),
    ) -> IntegrationResult:
        """Merge one worker branch into the integration branch.

        Parameters
        ----------
        repository_root:
            Path to the git repository root.
        integration_branch:
            The integration branch to merge into (e.g. ``integration`` or
            ``skillify/team/t1/integration``).
        worker_branch:
            The worker branch to merge from.
        worker_id:
            Identifier of the worker being merged (used in commit message and
            merge-plan tracking).
        merge_plan:
            The current ``MergePlan`` before this merge. A copy with updated
            fields (``current``, ``merged``, ``conflict``,
            ``integration_head``) is returned as part of the result.
        merge_plan_path:
            If provided, the updated merge-plan is also written to this path
            atomically after the merge step completes.
        verification_commands:
            Shell commands to run after a successful merge, in order. Failures
            are recorded but do not block integration commit generation.

        Returns
        -------
        ``IntegrationResult`` with the full merge outcome.
        """
        # 1. Ensure on integration branch
        _run_git(["checkout", integration_branch], cwd=repository_root)

        # 2. Attempt merge
        merge_result = subprocess.run(
            [
                "git", "merge", "--no-ff", worker_branch,
                "-m", f"Merge worker {worker_id} into integration",
            ],
            cwd=str(repository_root),
            capture_output=True, text=True, check=False,
        )

        success = merge_result.returncode == 0
        conflict_files: tuple[str, ...] = ()
        conflict_details: str | None = None
        integration_commit: str | None = None
        verification_results: tuple[tuple[str, int, str, str], ...] = ()

        if not success:
            # 3. Conflict -- record files, do NOT abort (keep working tree
            #    intact for manual resolution by the integration pane).
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=str(repository_root),
                capture_output=True, text=True, check=False,
            )
            files = [f for f in diff_result.stdout.splitlines() if f.strip()]
            conflict_files = tuple(files)
            conflict_details = (
                f"Conflict during merge of worker '{worker_id}' "
                f"(branch '{worker_branch}') into '{integration_branch}': "
                f"{len(conflict_files)} conflicted file(s)"
            )
        else:
            # 4. Merge succeeded -- run verification commands
            head_result = _run_git(["rev-parse", "HEAD"], cwd=repository_root)
            integration_commit = head_result.stdout.strip()

            verif_results: list[tuple[str, int, str, str]] = []
            for cmd in verification_commands:
                result = subprocess.run(
                    cmd, shell=True, cwd=str(repository_root),
                    capture_output=True, text=True, check=False,
                )
                verif_results.append(
                    (cmd, result.returncode, result.stdout, result.stderr),
                )
            verification_results = tuple(verif_results)

        # 5. Build updated merge-plan (record current HEAD even on conflict)
        head_result = _run_git(["rev-parse", "HEAD"], cwd=repository_root)
        integration_head = head_result.stdout.strip()

        new_merged = list(merge_plan.merged)
        if success:
            new_merged.append(worker_id)
        updated_plan = MergePlan(
            order=merge_plan.order,
            current=worker_id,
            merged=tuple(new_merged),
            conflict=not success,
            integration_head=integration_head,
        )

        # 6. Persist merge-plan if path provided
        if merge_plan_path is not None:
            updated_plan.write(merge_plan_path)

        return IntegrationResult(
            success=success,
            integration_commit=integration_commit,
            conflict_files=conflict_files,
            conflict_details=conflict_details,
            verification_results=verification_results,
            merge_plan_updated=updated_plan,
        )


def _run_git(args: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command and raise on failure."""
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result
