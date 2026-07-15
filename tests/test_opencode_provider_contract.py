from __future__ import annotations

import base64
import json
import signal
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import requests

from skillify.agent.events import EventType, TaskState
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec, TaskSpec
from skillify.agent.providers.opencode import OpenCodeError, OpenCodeProvider, ProviderCrashed, ProviderTimeout

NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


class FakeProcess:
    pid = 4242
    def __init__(self) -> None: self.returncode = None
    def poll(self): return self.returncode
    def wait(self, timeout=None): self.returncode = 0; return 0


class Handler(BaseHTTPRequestHandler):
    events: list[dict[str, object]] = []
    requests: list[tuple[str, str, str]] = []
    def log_message(self, format, *args): return
    def _json(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        type(self).requests.append(("GET", self.path, self.headers.get("Authorization", "")))
        if self.path == "/global/health": return self._json({"healthy": True, "version": "1.15.11"})
        if self.path == "/event":
            body = b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in type(self).events)
            self.send_response(200); self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        self._json({}, 404)
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0")); raw = self.rfile.read(length).decode()
        type(self).requests.append(("POST", self.path, self.headers.get("Authorization", "")))
        if self.path == "/session": return self._json({"id": "session-1"})
        if self.path.endswith("/prompt_async"): self.send_response(204); self.end_headers(); return
        if self.path.endswith("/abort") or self.path == "/instance/dispose": return self._json(True)
        self._json({"body": raw}, 404)


@pytest.fixture()
def fake_server():
    Handler.events = []; Handler.requests = []
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield server
    server.shutdown(); thread.join(timeout=2)


def _runtime() -> ModelRuntimeConfig:
    return ModelRuntimeConfig("internal", "https://model.intranet.example/v1", "code-1",
                              ("model.intranet.example",), ("MODEL_KEY",))


def _spec(tmp_path: Path) -> ProviderStartSpec:
    workspace = (tmp_path / "repo").resolve(); workspace.mkdir(parents=True)
    return ProviderStartSpec(workspace, (workspace,), tmp_path / "config", _runtime(), 1.0, 1.0)


def _provider(fake_server, monkeypatch, process=None, monotonic=None):
    captured = {}; killed = []; process = process or FakeProcess()
    def popen(argv, **kwargs): captured.update(argv=argv, kwargs=kwargs); return process
    monkeypatch.setenv("MODEL_KEY", "top-secret")
    provider = OpenCodeProvider(
        popen=popen, port_factory=lambda: fake_server.server_port,
        password_factory=lambda: "temporary-password", clock=lambda: NOW,
        monotonic=monotonic or (lambda: 0.0), sleep=lambda value: None,
        killpg=lambda pgid, sig: killed.append((pgid, sig)),
        getpgid=lambda pid: pid, process_start_token=lambda pid: "start-100",
    )
    return provider, captured, killed, process


def test_start_is_local_authenticated_isolated_and_pipe_safe(tmp_path, fake_server, monkeypatch):
    provider, captured, _, _ = _provider(fake_server, monkeypatch)
    handle = provider.start(_spec(tmp_path))
    assert captured["argv"] == ["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(fake_server.server_port)]
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["stdout"] is captured["kwargs"]["stderr"] is __import__("subprocess").DEVNULL
    assert handle.base_url.startswith("http://127.0.0.1:")
    auth = "Basic " + base64.b64encode(b"opencode:temporary-password").decode()
    assert Handler.requests[0] == ("GET", "/global/health", auth)
    config = (tmp_path / "config/opencode.json").read_text(encoding="utf-8")
    assert "top-secret" not in config and "temporary-password" not in config
    assert json.loads(config)["provider"]["internal"]["options"]["baseURL"] == "https://model.intranet.example/v1"


def test_normal_completion_maps_only_safe_events(tmp_path, fake_server, monkeypatch):
    Handler.events = [
        {"type": "todo.updated", "properties": {"sessionID": "session-1", "todos": [{"id": "1"}]}},
        {"type": "permission.asked", "properties": {"sessionID": "session-1", "id": "call-1", "permission": "bash", "prompt": "private"}},
        {"type": "message.part.updated", "properties": {"sessionID": "session-1", "part": {"type": "tool", "tool": "test", "callID": "call-2", "state": {"status": "completed", "output": "private source", "metadata": {"exit": 0}}}}},
        {"type": "session.diff", "properties": {"sessionID": "session-1", "diff": [{"file": "secret.py", "before": "source"}]}},
        {"type": "session.idle", "properties": {"sessionID": "session-1"}},
    ]
    provider, _, _, _ = _provider(fake_server, monkeypatch)
    handle = provider.start(_spec(tmp_path)); session = provider.create_session(handle, TaskSpec("task-1", "private prompt"))
    assert "private prompt" not in repr(provider._tasks)
    events = list(provider.stream_events(handle, session))
    assert [e.type for e in events] == [EventType.TASK_ACCEPTED, EventType.PLAN_READY, EventType.TOOL_REQUESTED, EventType.TEST_COMPLETED, EventType.ARTIFACT_CREATED, EventType.TASK_FINISHED]
    assert events[-1].state is TaskState.SUCCEEDED
    assert "private" not in repr(events) and "source" not in repr(events) and "secret.py" not in repr(events)
    assert provider._tasks == {}


def test_cancel_timeout_crash_and_stop_cleanup(tmp_path, fake_server, monkeypatch):
    provider, _, killed, process = _provider(fake_server, monkeypatch)
    handle = provider.start(_spec(tmp_path)); session = provider.create_session(handle, TaskSpec("task-1", "private"))
    assert provider.cancel(handle, session).state is TaskState.CANCELLED
    assert Handler.requests[-1][1] == "/session/session-1/abort"
    assert provider._tasks == {}
    assert provider.stop(handle).state is TaskState.SUCCEEDED
    assert killed and process.returncode == 0
    assert provider.stop(handle).state is TaskState.SUCCEEDED

    crashed = FakeProcess()
    provider2, _, _, _ = _provider(fake_server, monkeypatch, process=crashed)
    handle2 = provider2.start(_spec(tmp_path / "second")); session2 = provider2.create_session(handle2, TaskSpec("task-2", "private")); crashed.returncode = 9
    with pytest.raises(ProviderCrashed): list(provider2.stream_events(handle2, session2))


def test_timeout_emits_blocked_then_failed(tmp_path, fake_server, monkeypatch):
    Handler.events = []
    values = iter((0.0, 0.0, 2.0))
    provider, _, _, _ = _provider(fake_server, monkeypatch, monotonic=lambda: next(values))
    handle = provider.start(_spec(tmp_path)); session = provider.create_session(
        handle, TaskSpec("task-timeout", "private", timeout_seconds=1.0)
    )
    events = list(provider.stream_events(handle, session))
    assert [(event.type, event.state) for event in events[-2:]] == [
        (EventType.TASK_BLOCKED, TaskState.BLOCKED),
        (EventType.TASK_FINISHED, TaskState.FAILED),
    ]
    assert events[-1].details["reason_code"] == "PROVIDER_TIMEOUT"
    assert Handler.requests[-1][1] == "/session/session-1/abort"


def test_unhealthy_startup_deadline_terminates_process_group(tmp_path, monkeypatch):
    class Unhealthy:
        def request_json(self, *args, **kwargs): return {"healthy": False, "version": "1.15.11"}
    process = FakeProcess(); killed = []; values = iter((0.0, 0.0, 2.0))
    monkeypatch.setenv("MODEL_KEY", "top-secret")
    provider = OpenCodeProvider(
        transport=Unhealthy(), popen=lambda argv, **kwargs: process,
        port_factory=lambda: 32123, password_factory=lambda: "temporary-password",
        monotonic=lambda: next(values), sleep=lambda value: None,
        killpg=lambda pgid, sig: killed.append((pgid, sig)), getpgid=lambda pid: pid,
        process_start_token=lambda pid: "start-100",
    )
    with pytest.raises(ProviderTimeout): provider.start(_spec(tmp_path))
    assert killed == [(4242, signal.SIGTERM)]
    assert process.returncode == 0 and provider._live == {}


def test_healthy_response_without_version_terminates_started_process(tmp_path, monkeypatch):
    class MissingVersion:
        def request_json(self, *args, **kwargs): return {"healthy": True}
    process = FakeProcess(); killed = []
    monkeypatch.setenv("MODEL_KEY", "top-secret")
    provider = OpenCodeProvider(
        transport=MissingVersion(), popen=lambda argv, **kwargs: process,
        port_factory=lambda: 32123, password_factory=lambda: "temporary-password",
        monotonic=lambda: 0.0, sleep=lambda value: None,
        killpg=lambda pgid, sig: killed.append((pgid, sig)), getpgid=lambda pid: pid,
        process_start_token=lambda pid: "start-100",
    )
    with pytest.raises(OpenCodeError, match="omitted version"): provider.start(_spec(tmp_path))
    assert killed == [(4242, signal.SIGTERM)]
    assert process.returncode == 0 and provider._live == {}


def test_sse_network_error_is_redacted_failed_result_and_aborts(tmp_path, fake_server, monkeypatch):
    provider, _, _, _ = _provider(fake_server, monkeypatch)
    handle = provider.start(_spec(tmp_path)); session = provider.create_session(handle, TaskSpec("task-1", "private"))
    working_transport = provider.transport
    class BrokenSSE:
        def request_json(self, *args, **kwargs): return working_transport.request_json(*args, **kwargs)
        def iter_sse(self, *args, **kwargs):
            raise requests.ConnectionError("secret network detail")
            yield
    provider.transport = BrokenSSE()
    events = list(provider.stream_events(handle, session))
    assert [event.details["reason_code"] for event in events[-2:]] == ["PROVIDER_NETWORK", "PROVIDER_NETWORK"]
    assert "secret network detail" not in repr(events)
    assert Handler.requests[-1][1] == "/session/session-1/abort"


def test_foreign_session_events_are_ignored(tmp_path, fake_server, monkeypatch):
    Handler.events = [
        {"type": "session.error", "properties": {"sessionID": "other", "error": {"name": "SecretError"}}},
        {"type": "session.idle", "properties": {"sessionID": "session-1"}},
    ]
    provider, _, _, _ = _provider(fake_server, monkeypatch)
    handle = provider.start(_spec(tmp_path)); session = provider.create_session(handle, TaskSpec("task-1", "private"))
    events = list(provider.stream_events(handle, session))
    assert [event.type for event in events] == [EventType.TASK_ACCEPTED, EventType.TASK_FINISHED]


def test_runtime_state_is_atomic_redacted_and_cross_cli_stoppable(tmp_path, monkeypatch):
    from skillify.cli.agent_cmd import AgentRuntimeState, stop_owned_process, write_runtime_state
    from skillify.common.config import load_agent_paths
    paths = load_agent_paths({"SKILLIFY_AGENT_STATE_DIR": str(tmp_path / "state")}, home=tmp_path)
    state = AgentRuntimeState(1, __import__("os").getuid(), 4242, 4242, "start-100", "opencode",
                              "workspace-sha256", "task-1", "session-1", "1.15.11",
                              "2026-07-16T00:00:00+00:00", "running")
    write_runtime_state(paths, state)
    text = paths.runtime_path.read_text(encoding="utf-8")
    assert paths.runtime_path.stat().st_mode & 0o777 == 0o600
    assert "password" not in text and "prompt" not in text and "MODEL_KEY" not in text
    class Inspector:
        waits = iter((False, True))
        def is_alive(self, pid): return True
        def pgid(self, pid): return 4242
        def start_token(self, pid): return "start-100"
        def executable(self, pid): return "/opt/skillify/opencode"
        def wait_exited(self, pid, timeout): return next(self.waits)
    killed = []
    assert stop_owned_process(paths, Inspector(), lambda pgid, sig: killed.append((pgid, sig))) is True
    assert killed == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]
    assert not paths.runtime_path.exists()


def test_stale_or_reused_pid_is_cleared_without_signal(tmp_path):
    from skillify.cli.agent_cmd import AgentRuntimeState, stop_owned_process, write_runtime_state
    from skillify.common.config import load_agent_paths
    paths = load_agent_paths({"SKILLIFY_AGENT_STATE_DIR": str(tmp_path / "state")}, home=tmp_path)
    state = AgentRuntimeState(1, __import__("os").getuid(), 4242, 4242, "old", "opencode",
                              "workspace", "task", "session", "1.15.11", "time", "running")
    write_runtime_state(paths, state)
    class Reused:
        def is_alive(self, pid): return True
        def pgid(self, pid): return 4242
        def start_token(self, pid): return "new"
        def executable(self, pid): return "/opt/skillify/opencode"
        def wait_exited(self, pid, timeout): raise AssertionError("must not wait")
    killed = []
    assert stop_owned_process(paths, Reused(), lambda pgid, sig: killed.append(pgid)) is False
    assert killed == [] and not paths.runtime_path.exists()


def test_cross_cli_stop_keeps_state_when_sigkill_cannot_confirm_exit(tmp_path):
    from skillify.cli.agent_cmd import AgentRuntimeState, stop_owned_process, write_runtime_state
    from skillify.common.config import load_agent_paths
    paths = load_agent_paths({"SKILLIFY_AGENT_STATE_DIR": str(tmp_path / "state")}, home=tmp_path)
    state = AgentRuntimeState(1, __import__("os").getuid(), 4242, 4242, "start-100", "opencode",
                              "workspace", "task", "session", "1.15.11", "time", "running")
    write_runtime_state(paths, state)
    class Stuck:
        def is_alive(self, pid): return True
        def pgid(self, pid): return 4242
        def start_token(self, pid): return "start-100"
        def executable(self, pid): return "/opt/skillify/opencode"
        def wait_exited(self, pid, timeout): return False
    killed = []
    assert stop_owned_process(paths, Stuck(), lambda pgid, sig: killed.append((pgid, sig))) is False
    assert killed == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]
    assert paths.runtime_path.exists()


def test_run_local_task_wires_provider_logs_events_and_always_cleans(tmp_path, monkeypatch):
    from dataclasses import replace
    from skillify.agent.events import TaskEvent
    from skillify.agent.provider import ProviderHandle, ProviderResult, ProviderSession
    from skillify.cli import agent_cmd
    from skillify.common.config import AgentLocalConfig, load_agent_paths
    calls = []
    class FakeProvider:
        def start(self, spec): calls.append("start"); return ProviderHandle("h", "opencode", "1.15.11", "http://127.0.0.1:9", 4242)
        def ownership(self, handle): return {"pid": 4242, "pgid": 4242, "start_token": "start-1", "executable": "opencode"}
        def create_session(self, handle, spec): calls.append("session"); return ProviderSession(spec.task_id, "session-1", handle.handle_id)
        def stream_events(self, handle, session):
            calls.append("stream")
            yield TaskEvent(session.task_id, session.session_id, "opencode", "1.15.11", 1, 1, NOW,
                            EventType.TASK_FINISHED, TaskState.SUCCEEDED, {"result_state": "succeeded"})
        def cancel(self, handle, session): calls.append("abort"); return ProviderResult(TaskState.CANCELLED)
        def stop(self, handle): calls.append("stop"); return ProviderResult(TaskState.SUCCEEDED)
    monkeypatch.setattr(agent_cmd, "_build_provider", lambda: FakeProvider())
    monkeypatch.setenv("MODEL_KEY", "top-secret")
    paths = load_agent_paths({
        "SKILLIFY_AGENT_CONFIG_DIR": str(tmp_path / "config"),
        "SKILLIFY_AGENT_STATE_DIR": str(tmp_path / "state"),
        "SKILLIFY_AGENT_CACHE_DIR": str(tmp_path / "cache"),
        "SKILLIFY_AGENT_LOG_DIR": str(tmp_path / "log"),
    }, home=tmp_path)
    workspace = (tmp_path / "repo").resolve(); workspace.mkdir()
    config = AgentLocalConfig(
        allowed_workspaces=(str(workspace),), model_endpoint="https://model.intranet.example/v1",
        model_provider="internal", model_name="code-1", allowed_model_hosts=("model.intranet.example",),
        credential_env_names=("MODEL_KEY",),
    )
    assert agent_cmd._run_local_task(workspace, "private prompt", paths, config) == "succeeded"
    assert calls == ["start", "session", "stream", "abort", "stop"]
    assert not paths.runtime_path.exists()
    log = paths.log_path.read_text(encoding="utf-8")
    assert "private prompt" not in log and "top-secret" not in log and "MODEL_KEY" not in log


def test_run_local_task_cleans_start_and_stream_failures(tmp_path, monkeypatch):
    from skillify.cli import agent_cmd
    from skillify.cli.agent_cmd import AgentCommandFailure
    from skillify.common.config import AgentLocalConfig, load_agent_paths
    class StartFailure:
        def start(self, spec): raise RuntimeError("secret start detail")
    monkeypatch.setattr(agent_cmd, "_build_provider", lambda: StartFailure())
    paths = load_agent_paths({"SKILLIFY_AGENT_STATE_DIR": str(tmp_path / "state"),
                              "SKILLIFY_AGENT_LOG_DIR": str(tmp_path / "log")}, home=tmp_path)
    workspace = (tmp_path / "repo").resolve(); workspace.mkdir()
    config = AgentLocalConfig(
        allowed_workspaces=(str(workspace),), model_endpoint="https://model.intranet.example/v1",
        model_provider="internal", model_name="code-1", allowed_model_hosts=("model.intranet.example",),
        credential_env_names=("MODEL_KEY",),
    )
    with pytest.raises(AgentCommandFailure) as captured:
        agent_cmd._run_local_task(workspace, "private prompt", paths, config)
    assert captured.value.code is agent_cmd.AgentErrorCode.PROVIDER_FAILED
    assert not paths.runtime_path.exists()


def test_sigterm_unwinds_through_abort_stop_cleanup_and_restores_handler(tmp_path, monkeypatch):
    from skillify.agent.provider import ProviderHandle, ProviderResult, ProviderSession
    from skillify.cli import agent_cmd
    from skillify.common.config import AgentLocalConfig, load_agent_paths
    calls = []; installed = []; previous = object()
    class FakeProvider:
        def start(self, spec): return ProviderHandle("h", "opencode", "1.15.11", "http://127.0.0.1:9", 4242)
        def ownership(self, handle): return {"pid": 4242, "pgid": 4242, "start_token": "start-1", "executable": "opencode"}
        def create_session(self, handle, spec): return ProviderSession(spec.task_id, "session-1", handle.handle_id)
        def stream_events(self, handle, session):
            installed[0](signal.SIGTERM, None)
            yield
        def cancel(self, handle, session): calls.append("abort"); return ProviderResult(TaskState.CANCELLED)
        def stop(self, handle): calls.append("stop"); return ProviderResult(TaskState.SUCCEEDED)
    monkeypatch.setattr(agent_cmd, "_build_provider", lambda: FakeProvider())
    monkeypatch.setattr(agent_cmd.signal, "getsignal", lambda sig: previous)
    monkeypatch.setattr(agent_cmd.signal, "signal", lambda sig, handler: installed.append(handler))
    monkeypatch.setenv("MODEL_KEY", "top-secret")
    paths = load_agent_paths({"SKILLIFY_AGENT_STATE_DIR": str(tmp_path / "state"),
                              "SKILLIFY_AGENT_LOG_DIR": str(tmp_path / "log")}, home=tmp_path)
    workspace = (tmp_path / "repo").resolve(); workspace.mkdir()
    config = AgentLocalConfig(
        allowed_workspaces=(str(workspace),), model_endpoint="https://model.intranet.example/v1",
        model_provider="internal", model_name="code-1", allowed_model_hosts=("model.intranet.example",),
        credential_env_names=("MODEL_KEY",),
    )
    assert agent_cmd._run_local_task(workspace, "private", paths, config) == "cancelled"
    assert calls == ["abort", "stop"] and installed[-1] is previous
    assert not paths.runtime_path.exists()


def test_foreground_stop_failure_preserves_runtime_and_returns_provider_failed(tmp_path, monkeypatch):
    from skillify.agent.events import TaskEvent
    from skillify.agent.provider import ProviderHandle, ProviderResult, ProviderSession
    from skillify.cli import agent_cmd
    from skillify.cli.agent_cmd import AgentCommandFailure
    from skillify.common.config import AgentLocalConfig, load_agent_paths
    class StopFailure:
        def start(self, spec): return ProviderHandle("h", "opencode", "1.15.11", "http://127.0.0.1:9", 4242)
        def ownership(self, handle): return {"pid": 4242, "pgid": 4242, "start_token": "start-1", "executable": "opencode"}
        def create_session(self, handle, spec): return ProviderSession(spec.task_id, "session-1", handle.handle_id)
        def stream_events(self, handle, session):
            yield TaskEvent(session.task_id, session.session_id, "opencode", "1.15.11", 1, 1, NOW,
                            EventType.TASK_FINISHED, TaskState.SUCCEEDED, {"result_state": "succeeded"})
        def cancel(self, handle, session): return ProviderResult(TaskState.CANCELLED)
        def stop(self, handle): raise RuntimeError("process still alive")
    monkeypatch.setattr(agent_cmd, "_build_provider", lambda: StopFailure())
    monkeypatch.setenv("MODEL_KEY", "top-secret")
    paths = load_agent_paths({"SKILLIFY_AGENT_STATE_DIR": str(tmp_path / "state"),
                              "SKILLIFY_AGENT_LOG_DIR": str(tmp_path / "log")}, home=tmp_path)
    workspace = (tmp_path / "repo").resolve(); workspace.mkdir()
    config = AgentLocalConfig(
        allowed_workspaces=(str(workspace),), model_endpoint="https://model.intranet.example/v1",
        model_provider="internal", model_name="code-1", allowed_model_hosts=("model.intranet.example",),
        credential_env_names=("MODEL_KEY",),
    )
    with pytest.raises(AgentCommandFailure) as captured:
        agent_cmd._run_local_task(workspace, "private", paths, config)
    assert captured.value.code is agent_cmd.AgentErrorCode.PROVIDER_FAILED
    assert paths.runtime_path.exists()
