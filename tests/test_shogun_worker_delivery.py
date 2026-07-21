from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skillify.agent.shogun.worker_delivery import (
    WorkerDelivery,
    WorkerDeliveryError,
    collect_delivery,
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


def test_collect_delivery_succeeds_on_clean_worktree_with_a_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    (repo / "feature.py").write_text("x = 1\n", encoding="utf-8")
    _git(["add", "feature.py"], cwd=repo)
    _git(["commit", "-m", "add feature"], cwd=repo)
    worker_commit = _git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()

    delivery = collect_delivery(
        repo, base_commit, "skillify/team/t1/worker/w1",
        test_summary="12 passed", known_risks=("perf regression risk",),
    )

    assert isinstance(delivery, WorkerDelivery)
    assert delivery.worker_commit == worker_commit
    assert delivery.base_commit == base_commit
    assert delivery.branch == "skillify/team/t1/worker/w1"
    assert delivery.clean is True
    assert delivery.changed_files == (("A", "feature.py"),)
    assert delivery.test_summary == "12 passed"
    assert delivery.known_risks == ("perf regression risk",)


def test_collect_delivery_defaults_test_summary_and_known_risks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)

    delivery = collect_delivery(repo, base_commit, "skillify/team/t1/worker/w1")

    assert delivery.test_summary == ""
    assert delivery.known_risks == ()
    assert delivery.changed_files == ()


def test_collect_delivery_changed_files_matches_real_git_diff_name_status(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    (repo / "a.py").write_text("a\n", encoding="utf-8")
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-m", "modify and add"], cwd=repo)
    _git(["rm", "README.md"], cwd=repo)
    _git(["commit", "-m", "remove readme"], cwd=repo)
    worker_commit = _git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()

    expected_raw = _git(
        ["diff", "--name-status", f"{base_commit}..{worker_commit}"], cwd=repo,
    ).stdout
    expected = tuple(
        tuple(line.split("\t", 1)) for line in expected_raw.splitlines() if line.strip()
    )

    delivery = collect_delivery(repo, base_commit, "some-branch")

    assert delivery.changed_files == expected
    assert ("A", "a.py") in delivery.changed_files
    assert ("D", "README.md") in delivery.changed_files


def test_collect_delivery_raises_on_dirty_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    (repo / "README.md").write_text("uncommitted change\n", encoding="utf-8")

    with pytest.raises(WorkerDeliveryError):
        collect_delivery(repo, base_commit, "some-branch")


def test_collect_delivery_raises_on_untracked_file_present(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    (repo / "untracked.txt").write_text("stray file\n", encoding="utf-8")

    with pytest.raises(WorkerDeliveryError):
        collect_delivery(repo, base_commit, "some-branch")


def test_collect_delivery_raises_when_head_not_based_on_base_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)

    # Create an unrelated history that does not descend from base_commit.
    _git(["checkout", "--orphan", "unrelated"], cwd=repo)
    _git(["rm", "-rf", "--cached", "."], cwd=repo)
    (repo / "other.py").write_text("other\n", encoding="utf-8")
    _git(["add", "other.py"], cwd=repo)
    _git(["commit", "-m", "unrelated root"], cwd=repo)

    with pytest.raises(WorkerDeliveryError):
        collect_delivery(repo, base_commit, "unrelated")


def test_collect_delivery_raises_on_invalid_base_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    with pytest.raises(WorkerDeliveryError):
        collect_delivery(repo, "0" * 40, "some-branch")
