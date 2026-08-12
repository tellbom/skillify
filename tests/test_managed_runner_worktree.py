from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from skillify.agent.managed_runner import (
    ManagedTaskRunner,
    first_terminal_outcome,
    session_start_payload,
)
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec
from skillify.tasks.protocol import TaskEnvelope


def _git(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_existing_task_worktree_is_reused_after_pre_session_failure(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "Skillify Test")
    _git(repository, "config", "user.email", "skillify@example.test")
    (repository / "README.md").write_text("base\n", encoding="utf-8")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "base")
    base_commit = _git(repository, "rev-parse", "HEAD")
    now = datetime.now(timezone.utc)
    envelope = TaskEnvelope(
        task_id="task-retry",
        endpoint_id="endpoint-1",
        workflow_id="evidence-bugfix",
        workflow_version="1.0.0",
        workspace_alias="repo",
        parameters={"issueReference": "owner/repo#1"},
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        nonce="nonce",
        runtime="shogun",
        state_version=1,
        execution_mode="team",
        preferred_cli="opencode",
    )
    spec = ProviderStartSpec(
        workspace=repository.resolve(),
        allowed_paths=(repository.resolve(),),
        config_dir=(tmp_path / "config").resolve(),
        runtime=ModelRuntimeConfig(),
        execution_mode="team",
        preferred_cli="opencode",
    )
    runner = object.__new__(ManagedTaskRunner)

    first = runner._worker_workspace(envelope, spec, "worker-a", base_commit)
    second = runner._worker_workspace(envelope, spec, "worker-a", base_commit)

    assert second == first
    assert _git(second, "branch", "--show-current") == "skillify/task-retry/worker-a"


def test_first_terminal_provider_event_cannot_be_overwritten_by_idle() -> None:
    assert first_terminal_outcome(None, "provider.failed") == "provider.failed"
    assert (
        first_terminal_outcome("provider.failed", "provider.completed")
        == "provider.failed"
    )


def test_official_session_start_does_not_override_provider_model_configuration(
    tmp_path: Path,
) -> None:
    payload = session_start_payload(
        provider="claude-code",
        task_id="task-1",
        worker_id="worker-1",
        workspace=tmp_path.resolve(),
        prompt="fix issue",
        mcp_servers={"forgejo": {"command": "skillctl"}},
        mcp_allowed_tools=("mcp__forgejo__forgejo_get_issue",),
    )

    assert payload["provider"] == "claude-code"
    assert "model" not in payload
    assert "environment" not in payload
    assert payload["mcpServers"] == {"forgejo": {"command": "skillctl"}}
