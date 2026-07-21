"""Single-Worker diff-scope gate and cross-Worker changed-file overlap detection.

``check`` runs ``git diff --name-status base_commit..worker_commit``, normalises
every changed-file path (rejects absolute paths, ``..`` segments, symlink escape),
and verifies that every changed file is covered by ``allowed_paths`` and none is
covered by ``forbidden_paths``.  Returns a :class:`ScopeCheckResult` -- the
outcome is a business decision, not an exception.  Exceptions only fire for
operational failures (git command cannot run, commit cannot be resolved) or
invalid policy configuration (absolute / ``..`` entries in ``allowed_paths`` /
``forbidden_paths``).

``find_overlaps`` is a separate dimension check: given multiple Workers' changed
file lists, find which files are touched by more than one Worker.  Overlaps are
not a rejection -- they indicate elevated merge-conflict risk.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScopeCheckResult:
    """Result of a single-Worker diff-scope check.

    Attributes:
        accepted: ``True`` when every changed file is within ``allowed_paths``
            and no changed file is within ``forbidden_paths``.
        changed_files:  Raw ``(status, path)`` tuples from ``git diff
            --name-status``.
        violations:  Human-readable descriptions of every policy violation
            discovered.  Empty when ``accepted is True``.
        reason:  Short summary of the rejection, or ``None`` when accepted.
    """

    accepted: bool
    changed_files: tuple[tuple[str, str], ...]
    violations: tuple[str, ...]
    reason: str | None


def _run_git(args: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _raise_for_invalid_path_config(paths: Sequence[str], *, label: str) -> None:
    for path in paths:
        if not path:
            raise ValueError(f"{label} contains an empty path")
        if path.startswith("/"):
            raise ValueError(
                f"{label} path {path!r} is absolute; must be relative",
            )
        if ".." in Path(path).parts:
            raise ValueError(
                f"{label} path {path!r} contains '..' segment; must be bounded",
            )


def _path_matches(pattern: str, path: str) -> bool:
    """Return True if *path* matches *pattern* (exact or prefix).

    A pattern like ``src/`` matches any path under that directory;
    ``src/main.py`` matches only that exact file.
    """
    if path == pattern:
        return True
    prefix = pattern.rstrip("/") + "/"
    return path.startswith(prefix)


def _check_symlink_escape(
    repository_root: Path,
    changed_path: str,
    status: str,
) -> bool:
    """Return True when *changed_path* is a symlink pointing outside the repo.

    Deleted files (status ``D``) are skipped since they cannot be symlinks
    in the worktree.  Non-existent files are also skipped -- ``Path.resolve``
    on a non-existent path does not follow symlinks for the missing portion.
    """
    if status == "D":
        return False
    full_path = repository_root / changed_path
    if not full_path.exists():
        return False
    resolved = full_path.resolve()
    repo_root_resolved = repository_root.resolve()
    try:
        resolved.relative_to(repo_root_resolved)
    except ValueError:
        return True
    return False


def check(
    repository_root: Path,
    worker_commit: str,
    base_commit: str,
    allowed_paths: Sequence[str],
    forbidden_paths: Sequence[str] = (),
) -> ScopeCheckResult:
    """Check whether a Worker's changed files stay within allowed bounds.

    Steps
    1. Validate ``allowed_paths`` / ``forbidden_paths`` format (raises
       :class:`ValueError` on bad config).
    2. Verify ``worker_commit`` resolves (raises :class:`RuntimeError`).
    3. ``git diff --name-status`` between the two commits.
    4. For every changed file: normalise path, check bounds, accumulate
       violations.

    Returns :class:`ScopeCheckResult` --- not an exception for policy
    violations, only for operational failures or config errors.
    """
    _raise_for_invalid_path_config(allowed_paths, label="allowed_paths")
    _raise_for_invalid_path_config(forbidden_paths, label="forbidden_paths")

    # --- Verify worker_commit exists -------------------------------------------
    resolve_result = _run_git(
        ["rev-parse", "--verify", worker_commit],
        cwd=repository_root,
    )
    if resolve_result.returncode != 0:
        raise RuntimeError(
            f"could not resolve worker_commit {worker_commit}: "
            f"{resolve_result.stderr.strip()}",
        )

    # --- Run git diff -----------------------------------------------------------
    diff_result = _run_git(
        ["diff", "--name-status", f"{base_commit}..{worker_commit}"],
        cwd=repository_root,
    )
    if diff_result.returncode != 0:
        raise RuntimeError(
            f"git diff failed ({base_commit}..{worker_commit}): "
            f"{diff_result.stderr.strip()}",
        )

    # --- Parse diff output and check every changed file -------------------------
    changed_files: list[tuple[str, str]] = []
    violations: list[str] = []

    for line in diff_result.stdout.splitlines():
        if not line.strip():
            continue
        status, _, file_path = line.partition("\t")
        if not file_path:
            continue
        changed_files.append((status, file_path))

        # Reject absolute paths (defence-in-depth -- git diff always produces
        # relative paths, but a corrupted / specially crafted repo might not).
        if Path(file_path).is_absolute():
            violations.append(f"absolute path: {file_path}")
            continue

        # Reject paths containing '..' segments.
        if ".." in Path(file_path).parts:
            violations.append(f"path escape via '..': {file_path}")
            continue

        # Reject symlink escape (path resolves outside repository_root).
        if _check_symlink_escape(repository_root, file_path, status):
            violations.append(f"symlink escape: {file_path}")
            continue

        # Allowed-paths check.
        if allowed_paths:
            allowed = any(
                _path_matches(entry, file_path) for entry in allowed_paths
            )
        else:
            allowed = False

        # Forbidden-paths check.
        if forbidden_paths:
            forbidden = any(
                _path_matches(entry, file_path) for entry in forbidden_paths
            )
        else:
            forbidden = False

        if not allowed:
            violations.append(f"not in allowed_paths: {file_path}")
        elif forbidden:
            violations.append(f"in forbidden_paths: {file_path}")

    if violations:
        return ScopeCheckResult(
            accepted=False,
            changed_files=tuple(changed_files),
            violations=tuple(violations),
            reason="scope rejected: " + "; ".join(violations),
        )

    return ScopeCheckResult(
        accepted=True,
        changed_files=tuple(changed_files),
        violations=(),
        reason=None,
    )


def find_overlaps(
    deliveries: Mapping[str, Sequence[str]],
) -> dict[str, tuple[str, ...]]:
    """Find files changed by more than one Worker.

    *deliveries* maps a Worker ID to its list of changed-file paths.  Returns a
    dict from each overlapping file path to the tuple of Worker IDs that changed
    it (sorted for determinism).  Only files changed by **two or more** Workers
    are included.

    Overlaps are *not* a rejection signal -- they indicate elevated merge-
    conflict risk and can be used to adjust merge-plan ordering.
    """
    file_to_workers: dict[str, set[str]] = {}
    for worker_id, files in deliveries.items():
        for file_path in files:
            file_to_workers.setdefault(file_path, set()).add(worker_id)

    return {
        path: tuple(sorted(workers))
        for path, workers in file_to_workers.items()
        if len(workers) > 1
    }
