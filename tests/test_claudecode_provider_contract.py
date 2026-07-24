from __future__ import annotations

import json
import signal
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from skillify.agent.events import EventType, TaskState
from skillify.agent.permissions import PermissionManifest, merge_permissions
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec, TaskSpec
from skillify.agent.providers.claudecode import ClaudeCodeProvider


NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)


class Input:
    def __init__(self): self.value = ""
    def write(self, value): self.value += value
    def close(self): pass


class Process:
    def __init__(self, lines=(), returncode=0):
        self.pid = 4242; self.stdin = Input(); self.stdout = iter(lines); self.returncode = returncode
    def poll(self): return self.returncode
    def wait(self, timeout=None): return self.returncode


def _spec(tmp_path: Path) -> ProviderStartSpec:
    workspace = (tmp_path / "repo").resolve(); workspace.mkdir(parents=True)
    return ProviderStartSpec(
        workspace, (workspace,), tmp_path / "config",
        ModelRuntimeConfig(
            "anthropic", "https://model.internal/v1", "claude-internal",
            ("model.internal",), ("CLAUDE_TOKEN",),
        ),
    )


def _provider(monkeypatch, process: Process, *, monotonic=lambda: 0.0):
    captured = {}; killed = []
    monkeypatch.setenv("CLAUDE_TOKEN", "top-secret")
    def popen(argv, **kwargs): captured.update(argv=argv, kwargs=kwargs); return process
    def killpg(pgid, sig): killed.append(sig); process.returncode = -sig
    provider = ClaudeCodeProvider(
        popen=popen, which=lambda name: "/opt/skillify/claude",
        version_runner=lambda argv: "1.2.3\n", killpg=killpg,
        getpgid=lambda pid: pid, clock=lambda: NOW, monotonic=monotonic,
    )
    return provider, captured, killed


def test_normal_stream_json_maps_to_contract_without_persisting_secret(tmp_path, monkeypatch) -> None:
    process = Process([
        json.dumps({"type": "assistant"}) + "\n",
        json.dumps({"type": "user"}) + "\n",
        json.dumps({"type": "result", "is_error": False}) + "\n",
    ])
    provider, captured, _ = _provider(monkeypatch, process)
    handle = provider.start(_spec(tmp_path)); session = provider.create_session(handle, TaskSpec("task-1", "private task"))
    events = list(provider.stream_events(handle, session))
    assert events[-1].type is EventType.TASK_FINISHED and events[-1].state is TaskState.SUCCEEDED
    assert "private task" not in " ".join(captured["argv"])
    assert process.stdin.value == "private task"
    assert captured["kwargs"]["cwd"] == str((tmp_path / "repo").resolve())
    assert captured["kwargs"]["env"]["CLAUDE_TOKEN"] == "top-secret"
    assert not (tmp_path / "config").exists()
    provider.stop(handle)


def test_provider_owned_runtime_uses_claude_settings_without_model_override(tmp_path, monkeypatch) -> None:
    user_home = tmp_path / "home"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    workspace = (tmp_path / "owned-repo").resolve()
    workspace.mkdir()
    spec = ProviderStartSpec(workspace, (workspace,), tmp_path / "config", ModelRuntimeConfig())
    process = Process([json.dumps({"type": "result", "is_error": False}) + "\n"])
    provider, captured, _ = _provider(monkeypatch, process)

    handle = provider.start(spec)
    provider.create_session(handle, TaskSpec("task-owned", "work"))

    assert "--model" not in captured["argv"]
    assert captured["kwargs"]["env"]["HOME"] == str(user_home)
    assert "ANTHROPIC_BASE_URL" not in captured["kwargs"]["env"]
    assert "ANTHROPIC_MODEL" not in captured["kwargs"]["env"]
    assert "CLAUDE_TOKEN" not in captured["kwargs"]["env"]


def test_task_mcp_tools_are_allowed_and_permission_denial_fails(tmp_path, monkeypatch) -> None:
    process = Process([
        json.dumps({
            "type": "user",
            "message": {"content": [{"type": "tool_result", "is_error": True}]},
            "toolUseResult": "Claude requested permissions, but you haven't granted it yet.",
        }) + "\n",
        json.dumps({"type": "result", "is_error": False}) + "\n",
    ])
    provider, captured, _ = _provider(monkeypatch, process)
    spec = _spec(tmp_path)
    spec = replace(
        spec,
        mcp_servers={"catalog": {"type": "stdio", "command": "catalog"}},
        mcp_allowed_tools=("mcp__catalog__skills_search",),
        permissions=merge_permissions((PermissionManifest.from_value("task", {
            "writePaths": ["**/*"],
        }),)),
    )

    handle = provider.start(spec)
    session = provider.create_session(handle, TaskSpec("task-mcp", "work"))
    events = list(provider.stream_events(handle, session))

    assert "--permission-mode" in captured["argv"]
    assert "acceptEdits" in captured["argv"]
    assert captured["argv"][-2:] == ["--allowedTools", "mcp__catalog__skills_search"]
    assert events[-1].state is TaskState.FAILED
    assert events[-1].details["reason_code"] == "CLAUDE_CODE_PERMISSION_DENIED"


def test_cancel_terminates_process_group(tmp_path, monkeypatch) -> None:
    process = Process([], returncode=None)
    provider, _, killed = _provider(monkeypatch, process)
    handle = provider.start(_spec(tmp_path)); session = provider.create_session(handle, TaskSpec("task-1", "task"))
    assert provider.cancel(handle, session).state is TaskState.CANCELLED
    assert killed == [signal.SIGTERM]


def test_timeout_maps_blocked_then_failed(tmp_path, monkeypatch) -> None:
    values = iter((0.0, 2.0))
    process = Process([json.dumps({"type": "assistant"}) + "\n"], returncode=None)
    provider, _, _ = _provider(monkeypatch, process, monotonic=lambda: next(values))
    handle = provider.start(_spec(tmp_path)); session = provider.create_session(
        handle, TaskSpec("task-1", "task", timeout_seconds=1),
    )
    events = list(provider.stream_events(handle, session))
    assert [item.state for item in events[-2:]] == [TaskState.BLOCKED, TaskState.FAILED]


def test_crash_and_external_sigterm_have_distinct_terminal_states(tmp_path, monkeypatch) -> None:
    crashed = Process([], returncode=9)
    provider, _, _ = _provider(monkeypatch, crashed)
    handle = provider.start(_spec(tmp_path / "crash")); session = provider.create_session(handle, TaskSpec("task-1", "task"))
    assert list(provider.stream_events(handle, session))[-1].state is TaskState.FAILED

    terminated = Process([], returncode=-signal.SIGTERM)
    provider2, _, _ = _provider(monkeypatch, terminated)
    handle2 = provider2.start(_spec(tmp_path / "term")); session2 = provider2.create_session(handle2, TaskSpec("task-2", "task"))
    assert list(provider2.stream_events(handle2, session2))[-1].state is TaskState.CANCELLED
