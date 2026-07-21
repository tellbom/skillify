"""Tests for the Shogun IntegrationEngine -- deterministic git merge tool.

All tests use real temporary git repositories to verify git-level behavior:
clean merges, conflict detection, verification command execution, merge-plan
persistence, and the structural guarantee that IntegrationEngine exposes no
self-scheduling or lifecycle methods.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skillify.agent.shogun.integration import IntegrationEngine, IntegrationResult
from skillify.agent.shogun.registry import MergePlan


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def _init_repo(repo: Path) -> str:
    """Initialise a fresh git repo with a main branch and an integration branch."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(["init"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    _git(["branch", "-m", "main"], cwd=repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=repo)
    _git(["commit", "-m", "initial"], cwd=repo)
    _git(["branch", "integration"], cwd=repo)
    result = _git(["rev-parse", "HEAD"], cwd=repo)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

class TestMergeWorker:
    """Tests for IntegrationEngine.merge_worker."""

    def test_different_files_succeeds(self, tmp_path: Path) -> None:
        """Different workers modifying different files -> clean auto-merge."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        # worker-a adds file_a.py
        _git(["checkout", "-b", "worker-a"], cwd=repo)
        (repo / "file_a.py").write_text("a_content\n", encoding="utf-8")
        _git(["add", "file_a.py"], cwd=repo)
        _git(["commit", "-m", "worker a adds file_a"], cwd=repo)

        # worker-b adds file_b.py (from main)
        _git(["checkout", "main"], cwd=repo)
        _git(["checkout", "-b", "worker-b"], cwd=repo)
        (repo / "file_b.py").write_text("b_content\n", encoding="utf-8")
        _git(["add", "file_b.py"], cwd=repo)
        _git(["commit", "-m", "worker b adds file_b"], cwd=repo)

        merge_plan = MergePlan(
            order=("worker-a", "worker-b"),
            current=None, merged=(), conflict=False, integration_head=None,
        )

        result = IntegrationEngine.merge_worker(
            repository_root=repo,
            integration_branch="integration",
            worker_branch="worker-a",
            worker_id="worker-a",
            merge_plan=merge_plan,
        )

        assert result.success is True
        assert result.integration_commit is not None
        assert result.conflict_files == ()
        assert result.conflict_details is None
        assert result.merge_plan_updated.current == "worker-a"
        assert result.merge_plan_updated.merged == ("worker-a",)
        assert result.merge_plan_updated.conflict is False
        assert result.merge_plan_updated.integration_head is not None

        # Verify the integration branch actually has the merged file
        _git(["checkout", "integration"], cwd=repo)
        assert (repo / "file_a.py").read_text(encoding="utf-8") == "a_content\n"

    def test_same_line_conflict_detected(self, tmp_path: Path) -> None:
        """Same file, same line changed on both branches -> conflict recorded, not silently resolved."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Add a shared file on the integration branch
        _git(["checkout", "integration"], cwd=repo)
        (repo / "shared.py").write_text("original\n", encoding="utf-8")
        _git(["add", "shared.py"], cwd=repo)
        _git(["commit", "-m", "add shared file on integration"], cwd=repo)

        # worker-a modifies shared.py
        _git(["checkout", "-b", "worker-a"], cwd=repo)
        (repo / "shared.py").write_text("worker_a_change\n", encoding="utf-8")
        _git(["add", "shared.py"], cwd=repo)
        _git(["commit", "-m", "worker a changes shared"], cwd=repo)

        # worker-b also modifies shared.py (from the same integration base)
        _git(["checkout", "integration"], cwd=repo)
        _git(["checkout", "-b", "worker-b"], cwd=repo)
        (repo / "shared.py").write_text("worker_b_change\n", encoding="utf-8")
        _git(["add", "shared.py"], cwd=repo)
        _git(["commit", "-m", "worker b changes shared"], cwd=repo)

        merge_plan = MergePlan(
            order=("worker-a", "worker-b"),
            current=None, merged=(), conflict=False, integration_head=None,
        )

        # Merge worker-a (should succeed)
        result_a = IntegrationEngine.merge_worker(
            repository_root=repo,
            integration_branch="integration",
            worker_branch="worker-a",
            worker_id="worker-a",
            merge_plan=merge_plan,
        )
        assert result_a.success is True

        # Merge worker-b (should conflict -- same file same line)
        result_b = IntegrationEngine.merge_worker(
            repository_root=repo,
            integration_branch="integration",
            worker_branch="worker-b",
            worker_id="worker-b",
            merge_plan=result_a.merge_plan_updated,
        )

        assert result_b.success is False
        assert result_b.integration_commit is None
        assert "shared.py" in result_b.conflict_files
        assert result_b.conflict_details is not None
        assert "Conflict" in result_b.conflict_details
        assert result_b.merge_plan_updated.current == "worker-b"
        # worker-b's merge conflicted -- it is not "merged" yet.
        assert result_b.merge_plan_updated.merged == ("worker-a",)
        assert result_b.merge_plan_updated.conflict is True
        assert result_b.merge_plan_updated.integration_head is not None

        # Verifying the tree still contains conflict markers (not aborted)
        shared_text = (repo / "shared.py").read_text(encoding="utf-8")
        assert "<<<<<<<" in shared_text, (
            "merge --abort was called (tree should be left intact for manual resolution)"
        )

    def test_verification_commands_executed(self, tmp_path: Path) -> None:
        """Verification commands run after a successful merge and results are recorded."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        _git(["checkout", "-b", "worker-verify"], cwd=repo)
        (repo / "feature.py").write_text("x = 1\n", encoding="utf-8")
        _git(["add", "feature.py"], cwd=repo)
        _git(["commit", "-m", "add feature"], cwd=repo)

        merge_plan = MergePlan(
            order=("worker-verify",),
            current=None, merged=(), conflict=False, integration_head=None,
        )

        marker = tmp_path / "verification_marker.txt"

        result = IntegrationEngine.merge_worker(
            repository_root=repo,
            integration_branch="integration",
            worker_branch="worker-verify",
            worker_id="worker-verify",
            merge_plan=merge_plan,
            verification_commands=[
                f"echo verified > \"{marker}\"",
                "git log --oneline -1",
            ],
        )

        assert result.success is True
        assert len(result.verification_results) == 2

        # First command: write marker file
        cmd0, rc0, stdout0, stderr0 = result.verification_results[0]
        assert rc0 == 0
        assert marker.read_text(encoding="utf-8").strip() == "verified"

        # Second command: git log should show the merge commit
        cmd1, rc1, stdout1, stderr1 = result.verification_results[1]
        assert rc1 == 0
        assert "Merge worker" in stdout1

    def test_merge_plan_persisted_after_merge(self, tmp_path: Path) -> None:
        """Merge-plan file is written atomically after each merge step when merge_plan_path is given."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        _git(["checkout", "-b", "worker-persist"], cwd=repo)
        (repo / "data.py").write_text("data = 42\n", encoding="utf-8")
        _git(["add", "data.py"], cwd=repo)
        _git(["commit", "-m", "add data"], cwd=repo)

        merge_plan_path = tmp_path / "plans" / "merge-plan.json"

        merge_plan = MergePlan(
            order=("worker-persist",),
            current=None, merged=(), conflict=False, integration_head=None,
        )

        IntegrationEngine.merge_worker(
            repository_root=repo,
            integration_branch="integration",
            worker_branch="worker-persist",
            worker_id="worker-persist",
            merge_plan=merge_plan,
            merge_plan_path=merge_plan_path,
        )

        assert merge_plan_path.exists()
        # Verify atomic write (no .tmp leftover)
        assert not merge_plan_path.with_suffix(".tmp").exists()

        reloaded = MergePlan.read(merge_plan_path)
        assert reloaded.current == "worker-persist"
        assert reloaded.merged == ("worker-persist",)
        assert reloaded.conflict is False
        assert reloaded.integration_head is not None

    def test_merge_plan_persisted_after_conflict(self, tmp_path: Path) -> None:
        """Merge-plan is also persisted when a conflict occurs."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        _git(["checkout", "integration"], cwd=repo)
        (repo / "shared.py").write_text("base\n", encoding="utf-8")
        _git(["add", "shared.py"], cwd=repo)
        _git(["commit", "-m", "add shared"], cwd=repo)

        _git(["checkout", "-b", "worker-a"], cwd=repo)
        (repo / "shared.py").write_text("aaa\n", encoding="utf-8")
        _git(["add", "shared.py"], cwd=repo)
        _git(["commit", "-m", "worker a"], cwd=repo)

        _git(["checkout", "integration"], cwd=repo)
        _git(["checkout", "-b", "worker-b"], cwd=repo)
        (repo / "shared.py").write_text("bbb\n", encoding="utf-8")
        _git(["add", "shared.py"], cwd=repo)
        _git(["commit", "-m", "worker b"], cwd=repo)

        merge_plan = MergePlan(
            order=("worker-a", "worker-b"),
            current=None, merged=(), conflict=False, integration_head=None,
        )
        merge_plan_path = tmp_path / "plans" / "merge-plan.json"

        result_a = IntegrationEngine.merge_worker(
            repository_root=repo,
            integration_branch="integration",
            worker_branch="worker-a",
            worker_id="worker-a",
            merge_plan=merge_plan,
        )
        assert result_a.success is True

        result_b = IntegrationEngine.merge_worker(
            repository_root=repo,
            integration_branch="integration",
            worker_branch="worker-b",
            worker_id="worker-b",
            merge_plan=result_a.merge_plan_updated,
            merge_plan_path=merge_plan_path,
        )
        assert result_b.success is False

        # Plan should still be persisted
        assert merge_plan_path.exists()
        reloaded = MergePlan.read(merge_plan_path)
        assert reloaded.conflict is True
        assert reloaded.current == "worker-b"
        # A worker with an unresolved conflict is not "merged" -- only
        # successfully-merged workers belong in `merged`.
        assert "worker-b" not in reloaded.merged
        assert reloaded.merged == ("worker-a",)


class TestStructuralGuarantees:
    """Structural assertions about the IntegrationEngine class."""

    def test_no_self_scheduling_methods(self) -> None:
        """IntegrationEngine must NOT expose schedule/start/poll/run_forever/run methods.

        This is a structural guarantee that the engine stays a pure merge tool
        and does not accidentally grow agent-scheduling capabilities.
        """
        forbidden = {"schedule", "start", "poll", "run_forever", "run"}
        members = {
            name for name in dir(IntegrationEngine)
            if not name.startswith("_")
        }
        intersection = members & forbidden
        assert not intersection, (
            f"IntegrationEngine exposes forbidden agent-scheduling method(s): "
            f"{intersection}"
        )

    def test_only_expected_public_methods(self) -> None:
        """The only public static method should be merge_worker."""
        members = {
            name for name in dir(IntegrationEngine)
            if not name.startswith("_")
        }
        assert members == {"merge_worker"}, (
            f"IntegrationEngine has unexpected public members: {members}"
        )

    def test_integration_result_is_frozen(self) -> None:
        """IntegrationResult should be a frozen dataclass (immutable)."""
        result = IntegrationResult(
            success=True,
            integration_commit="abc123",
            conflict_files=(),
            conflict_details=None,
            verification_results=(),
            merge_plan_updated=MergePlan(
                order=("w1",), current="w1", merged=("w1",),
                conflict=False, integration_head="abc123",
            ),
        )
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]
