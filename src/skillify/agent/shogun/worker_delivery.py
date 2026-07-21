"""Read git facts about what a Worker produced, as a delivery gate.

``collect_delivery`` only reads facts from git — whether ``worker_commit``
exists, whether it is a descendant of ``base_commit``, whether the worktree
is clean, and the list of changed files between ``base_commit`` and
``worker_commit``. It does not run tests, does not analyze risk, and does not
merge or touch any branch other than reading the worker's own worktree.
``test_summary`` and ``known_risks`` cannot be derived from git state, so
callers supply them directly; they are packaged into the returned
:class:`WorkerDelivery` unchanged.

Any git fact that fails the delivery gate (invalid/missing commit, commit not
based on ``base_commit``, dirty worktree) raises :class:`WorkerDeliveryError`
rather than being represented as a false-y field on a returned record, so
delivery failure is explicit at the type level.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class WorkerDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerDelivery:
    worker_commit: str
    base_commit: str
    branch: str
    changed_files: tuple[tuple[str, str], ...]
    clean: bool
    test_summary: str
    known_risks: tuple[str, ...]


def _run_git(args: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False,
    )


def collect_delivery(
    worktree: Path,
    base_commit: str,
    branch: str,
    *,
    test_summary: str = "",
    known_risks: Sequence[str] = (),
) -> WorkerDelivery:
    """Read the git facts of a Worker's delivery from its worktree.

    Raises ``WorkerDeliveryError`` if HEAD cannot be resolved, if HEAD is not
    a descendant of ``base_commit``, or if the worktree is not clean
    (``git status --porcelain`` is non-empty). On success, returns a
    ``WorkerDelivery`` with ``worker_commit`` set to HEAD and
    ``changed_files`` parsed from ``git diff --name-status base..HEAD``.
    """
    head_result = _run_git(["rev-parse", "HEAD"], cwd=worktree)
    if head_result.returncode != 0:
        raise WorkerDeliveryError(
            f"could not resolve HEAD in {worktree}: {head_result.stderr.strip()}"
        )
    worker_commit = head_result.stdout.strip()
    if not worker_commit:
        raise WorkerDeliveryError(f"HEAD is empty in {worktree}")

    ancestor_result = _run_git(
        ["merge-base", "--is-ancestor", base_commit, worker_commit], cwd=worktree,
    )
    if ancestor_result.returncode != 0:
        raise WorkerDeliveryError(
            f"worker commit {worker_commit} is not based on base commit {base_commit}"
        )

    status_result = _run_git(["status", "--porcelain"], cwd=worktree)
    if status_result.returncode != 0:
        raise WorkerDeliveryError(
            f"git status failed in {worktree}: {status_result.stderr.strip()}"
        )
    if status_result.stdout.strip():
        raise WorkerDeliveryError(f"worktree {worktree} is not clean")

    diff_result = _run_git(
        ["diff", "--name-status", f"{base_commit}..{worker_commit}"], cwd=worktree,
    )
    if diff_result.returncode != 0:
        raise WorkerDeliveryError(
            f"git diff failed in {worktree}: {diff_result.stderr.strip()}"
        )
    changed_files: list[tuple[str, str]] = []
    for line in diff_result.stdout.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        changed_files.append((status, path))

    return WorkerDelivery(
        worker_commit=worker_commit,
        base_commit=base_commit,
        branch=branch,
        changed_files=tuple(changed_files),
        clean=True,
        test_summary=test_summary,
        known_risks=tuple(known_risks),
    )
