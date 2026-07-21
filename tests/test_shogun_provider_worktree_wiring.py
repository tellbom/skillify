from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

if os.name != "posix":
    pytest.skip("Shogun provider is Linux-only", allow_module_level=True)

from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec
from skillify.agent.providers import shogun as shogun_module
from skillify.agent.providers.shogun import ShogunProvider
from skillify.agent.shogun.fake_runtime import FakeRuntime
from skillify.agent.shogun.registry import WorktreeRegistry
from skillify.agent.shogun.team_recovery import diagnose
from skillify.agent.shogun.worktree import WorktreeManager
from skillify.credentials.identities import AccessCredential


class Broker:
    profiles = {
        "model": SimpleNamespace(
            name="model", credential_ref="local://model", scopes=frozenset({"model.invoke"}),
        ),
    }

    def credential(self, profile, reference, scopes):
        return AccessCredential(
            "test-only-secret", "model", scopes,
            datetime.now(timezone.utc) + timedelta(minutes=5),
        )

    def clear(self, reason):
        pass


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


def _install_bundle(tmp_path: Path) -> Path:
    install = tmp_path / "bundle"
    install.mkdir()
    entrypoint = install / "shutsujin_departure.sh"
    entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")
    entrypoint.chmod(0o755)
    return install


def _stub_distribution(monkeypatch) -> None:
    monkeypatch.setattr(shogun_module, "load_manifest", lambda _: {})
    monkeypatch.setattr(shogun_module, "require_installable", lambda _: None)
    monkeypatch.setattr(shogun_module, "verify_artifact", lambda *_: None)
    monkeypatch.setattr(shogun_module, "check_bundle_layout", lambda *_: None)
    monkeypatch.setattr(
        shogun_module, "check_host_dependencies",
        lambda _: SimpleNamespace(available=True, detail="ready"),
    )


def _provider(tmp_path: Path, runtime: FakeRuntime, *, credential_broker=None) -> ShogunProvider:
    return ShogunProvider(
        manifest_path=tmp_path / "manifest.json",
        artifact_path=tmp_path / "bundle.tar.gz",
        install_root=_install_bundle(tmp_path),
        cache_root=tmp_path / "cache",
        runtime=runtime,
        credential_broker=credential_broker,
    )


def _spec(
    *, workspace: Path, run_dir: Path, base_commit: str, work_packages: tuple[dict[str, object], ...],
) -> ProviderStartSpec:
    return ProviderStartSpec(
        workspace, (workspace,), run_dir,
        ModelRuntimeConfig(
            "test", "https://model.internal", "model", ("model.internal",), ("MODEL_TOKEN",),
        ),
        execution_mode="team", preferred_cli="opencode",
        credential_refs={"MODEL_TOKEN": "local://model"},
        work_packages=work_packages,
        base_commit=base_commit,
        repository_root=workspace,
    )


def test_provider_start_spec_rejects_non_hex_base_commit(tmp_path: Path) -> None:
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    with pytest.raises(ValueError):
        ProviderStartSpec(
            workspace, (workspace,), tmp_path / "config",
            ModelRuntimeConfig(
                "test", "https://model.internal", "model", ("model.internal",), ("MODEL_TOKEN",),
            ),
            execution_mode="team", preferred_cli="opencode",
            base_commit="not-a-sha",
        )


def test_provider_start_spec_empty_base_commit_is_backward_compatible(tmp_path: Path) -> None:
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    spec = ProviderStartSpec(
        workspace, (workspace,), tmp_path / "config",
        ModelRuntimeConfig(
            "test", "https://model.internal", "model", ("model.internal",), ("MODEL_TOKEN",),
        ),
    )
    assert spec.base_commit == ""
    assert spec.repository_root is None


def test_start_creates_worktrees_and_registry_matching_live_git_state(
    tmp_path: Path, monkeypatch,
) -> None:
    _stub_distribution(monkeypatch)
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    runtime = FakeRuntime()
    provider = _provider(tmp_path, runtime, credential_broker=Broker())
    run_dir = (provider.cache_root / "task-1").resolve()
    spec = _spec(
        workspace=repo, run_dir=run_dir, base_commit=base_commit,
        work_packages=(
            {"id": "wp-1", "allowedPaths": ["src/a.py"]},
            {"id": "wp-2", "allowedPaths": ["src/b.py"]},
        ),
    )

    handle = provider.start(spec)

    registry_path = run_dir / "worktree-registry.json"
    assert registry_path.exists()
    registry = WorktreeRegistry.read(registry_path)
    assert registry.base_commit == base_commit
    assert len(registry.workers) == 2
    assert {worker.worker_id for worker in registry.workers} == {"ashigaru1", "ashigaru2"}

    report = WorktreeManager().inspect(registry)
    assert report.ok is True

    for worker in registry.workers:
        head = _git(["rev-parse", "HEAD"], cwd=worker.worktree).stdout.strip()
        assert head == base_commit

    provider.stop(handle)


def test_start_with_empty_work_packages_does_not_create_worktrees(
    tmp_path: Path, monkeypatch,
) -> None:
    _stub_distribution(monkeypatch)
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    runtime = FakeRuntime()
    provider = _provider(tmp_path, runtime, credential_broker=Broker())
    run_dir = (provider.cache_root / "task-1").resolve()
    spec = _spec(workspace=repo, run_dir=run_dir, base_commit=base_commit, work_packages=())

    handle = provider.start(spec)

    assert not (run_dir / "worktree-registry.json").exists()
    provider.stop(handle)


def test_start_worktree_create_failure_leaves_no_credential_channel(
    tmp_path: Path, monkeypatch,
) -> None:
    _stub_distribution(monkeypatch)
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    runtime = FakeRuntime()
    provider = _provider(tmp_path, runtime, credential_broker=Broker())
    run_dir = (provider.cache_root / "task-1").resolve()

    # Pre-create a branch that collides with the worker branch name, so
    # WorktreeManager.create() fails with WorktreeManagerError.
    _git(
        ["branch", f"skillify/team/{run_dir.name}/worker/ashigaru1"],
        cwd=repo,
    )

    spec = _spec(
        workspace=repo, run_dir=run_dir, base_commit=base_commit,
        work_packages=({"id": "wp-1", "allowedPaths": ["src/a.py"]},),
    )

    with pytest.raises(Exception):
        provider.start(spec)

    assert not provider._handles
    # No worktrees left registered in git's metadata for the repo.
    live = _git(["worktree", "list", "--porcelain"], cwd=repo).stdout
    assert live.count("worktree ") == 1  # only the main worktree remains
    # No tmux session was started -- worktree creation happens before
    # self.lifecycle.start(), so the runtime's "start" action must never fire.
    assert not any(action[0] == "start" for action in runtime.actions)


def test_start_end_to_end_worker_commit_then_diagnose(tmp_path: Path, monkeypatch) -> None:
    """The key end-to-end check: start() creates real worktrees, a worker
    commits real work in its worktree, and team_recovery.diagnose() -- S8's
    recovery reconciliation -- correctly reads back that live state from the
    registry start() wrote. This proves creation and diagnosis are wired
    through the same real files/branches, not just independently unit-tested.
    """
    _stub_distribution(monkeypatch)
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    runtime = FakeRuntime()
    provider = _provider(tmp_path, runtime, credential_broker=Broker())
    run_dir = (provider.cache_root / "task-1").resolve()
    spec = _spec(
        workspace=repo, run_dir=run_dir, base_commit=base_commit,
        work_packages=({"id": "wp-1", "allowedPaths": ["src/a.py"]},),
    )

    handle = provider.start(spec)

    registry_path = run_dir / "worktree-registry.json"
    registry = WorktreeRegistry.read(registry_path)
    worker_worktree = registry.workers[0].worktree
    (worker_worktree / "src").mkdir(parents=True, exist_ok=True)
    (worker_worktree / "src" / "a.py").write_text("print('hi')\n", encoding="utf-8")
    _git(["add", "src/a.py"], cwd=worker_worktree)
    _git(["commit", "-m", "worker change"], cwd=worker_worktree)

    diagnosis = diagnose(
        repository_root=repo,
        registry_path=registry_path,
        merge_plan_path=None,
        worktree_manager=WorktreeManager(),
    )

    assert diagnosis.status == "live"

    provider.stop(handle)
