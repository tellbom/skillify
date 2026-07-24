"""Claude Code headless CLI adapter for the AgentProvider contract."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator

from skillify.agent.events import EventType, TaskEvent, TaskState
from skillify.agent.provider import (
    ProviderCapability, ProviderHandle, ProviderProbe, ProviderResult,
    ProviderSession, ProviderStartSpec, TaskSpec,
)


class ClaudeCodeError(RuntimeError):
    pass


@dataclass
class _Runtime:
    spec: ProviderStartSpec
    version: str


@dataclass
class _SessionRuntime:
    process: object
    handle_id: str
    timeout_seconds: float
    started_at: float


class ClaudeCodeProvider:
    def __init__(
        self,
        *,
        executable: str = "claude",
        popen=subprocess.Popen,
        which=shutil.which,
        version_runner: Callable[[list[str]], str] | None = None,
        killpg=os.killpg,
        getpgid=os.getpgid,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic=time.monotonic,
    ) -> None:
        self.executable = executable; self.popen = popen; self.which = which
        self.version_runner = version_runner or self._version
        self.killpg = killpg; self.getpgid = getpgid
        self.clock = clock; self.monotonic = monotonic
        self._live: dict[str, _Runtime] = {}
        self._sessions: dict[str, _SessionRuntime] = {}

    @staticmethod
    def _version(argv: list[str]) -> str:
        return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=5).stdout

    def _probe(self) -> tuple[str | None, str | None]:
        path = self.which(self.executable)
        if path is None:
            return None, None
        try:
            version = self.version_runner([path, "--version"]).strip()
        except (OSError, subprocess.SubprocessError):
            return None, None
        return (path, version) if version else (None, None)

    def probe(self) -> ProviderProbe:
        path, version = self._probe()
        if path is None or version is None:
            return ProviderProbe(False, None, "CLAUDE_CODE_UNAVAILABLE")
        return ProviderProbe(True, ProviderCapability("claude-code", version))

    def start(self, spec: ProviderStartSpec) -> ProviderHandle:
        path, version = self._probe()
        if path is None or version is None:
            raise ClaudeCodeError("claude executable is unavailable")
        handle = ProviderHandle(uuid.uuid4().hex, "claude-code", version, "stdio://local", 0)
        self._live[handle.handle_id] = _Runtime(spec, version)
        return handle

    def _environment(self, spec: ProviderStartSpec) -> dict[str, str]:
        # Claude Code owns its login, model and endpoint settings.  Preserve the
        # normal user configuration roots and only apply an explicit managed
        # runtime when one was deliberately configured for an isolated runtime.
        env = {
            key: os.environ[key]
            for key in (
                "PATH", "LANG", "LC_ALL", "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                "USER", "LOGNAME", "SSH_AUTH_SOCK",
            )
            if key in os.environ
        }
        for name in spec.runtime.credential_env_names:
            if name not in os.environ:
                raise ClaudeCodeError(f"required credential variable {name} is unset")
            env[name] = os.environ[name]
        if not spec.runtime.is_provider_managed:
            assert spec.runtime.endpoint is not None and spec.runtime.model is not None
            env["ANTHROPIC_BASE_URL"] = spec.runtime.endpoint
            env["ANTHROPIC_MODEL"] = spec.runtime.model
        env["DISABLE_TELEMETRY"] = "1"
        return env

    def create_session(self, handle: ProviderHandle, spec: TaskSpec) -> ProviderSession:
        runtime = self._live.get(handle.handle_id)
        if runtime is None:
            raise ClaudeCodeError("unknown Claude Code handle")
        path, _ = self._probe()
        assert path is not None
        from skillify.agent.claudecode_config import write_task_mcp_config
        argv = [path, "-p", "--output-format", "stream-json", "--verbose"]
        if any(policy.write_paths for policy in runtime.spec.permissions.policies):
            argv.extend(["--permission-mode", "acceptEdits"])
        if not runtime.spec.runtime.is_provider_managed:
            assert runtime.spec.runtime.model is not None
            argv.extend(["--model", runtime.spec.runtime.model])
        mcp_path = write_task_mcp_config(runtime.spec.config_dir, runtime.spec.mcp_servers)
        if mcp_path is not None:
            argv.extend(["--mcp-config", str(mcp_path)])
        if runtime.spec.mcp_allowed_tools:
            argv.extend(["--allowedTools", *runtime.spec.mcp_allowed_tools])
        process = self.popen(
            argv,
            cwd=str(runtime.spec.workspace), env=self._environment(runtime.spec),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, start_new_session=True,
        )
        if process.stdin is None:
            raise ClaudeCodeError("claude stdin is unavailable")
        process.stdin.write(spec.prompt); process.stdin.close()
        session = ProviderSession(spec.task_id, uuid.uuid4().hex, handle.handle_id)
        self._sessions[session.session_id] = _SessionRuntime(
            process, handle.handle_id, spec.timeout_seconds, self.monotonic(),
        )
        return session

    def _event(self, handle, session, kind, state, sequence, details=None):
        values = {"sequence": sequence}; values.update(details or {})
        return TaskEvent(
            session.task_id, session.session_id, "claude-code", handle.provider_version,
            1, 1, self.clock(), kind, state, values,
        )

    def _terminate(self, process) -> None:
        if process.poll() is not None:
            return
        try:
            self.killpg(self.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.killpg(self.getpgid(process.pid), signal.SIGKILL)

    def stream_events(self, handle: ProviderHandle, session: ProviderSession) -> Iterator[TaskEvent]:
        runtime = self._sessions[session.session_id]; process = runtime.process; sequence = 1
        yield self._event(handle, session, EventType.TASK_ACCEPTED, TaskState.QUEUED, sequence)
        permission_denied = False
        try:
            for line in process.stdout or ():
                if self.monotonic() - runtime.started_at >= runtime.timeout_seconds:
                    self._terminate(process); sequence += 1
                    yield self._event(handle, session, EventType.TASK_BLOCKED, TaskState.BLOCKED, sequence, {"reason_code": "PROVIDER_TIMEOUT"})
                    sequence += 1
                    yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.FAILED, sequence, {"reason_code": "PROVIDER_TIMEOUT"})
                    return
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = value.get("type"); sequence += 1
                if kind == "user" and "haven't granted it yet" in line:
                    permission_denied = True
                if kind == "assistant":
                    yield self._event(handle, session, EventType.TOOL_REQUESTED, TaskState.RUNNING, sequence, {"tool_name": "claude-code"})
                elif kind == "user":
                    yield self._event(handle, session, EventType.TOOL_COMPLETED, TaskState.RUNNING, sequence, {"tool_name": "claude-code"})
                elif kind == "result":
                    failed = value.get("is_error") is True or permission_denied
                    yield self._event(
                        handle, session, EventType.TASK_FINISHED,
                        TaskState.FAILED if failed else TaskState.SUCCEEDED, sequence,
                        (
                            {"reason_code": "CLAUDE_CODE_PERMISSION_DENIED"}
                            if permission_denied
                            else {"reason_code": "CLAUDE_CODE_ERROR"}
                        ) if failed else {"result_state": "succeeded"},
                    )
                    return
            returncode = process.wait(timeout=1)
            sequence += 1
            if returncode == -signal.SIGTERM:
                yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.CANCELLED, sequence)
            else:
                yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.FAILED, sequence, {"reason_code": "CLAUDE_CODE_CRASHED"})
        finally:
            self._sessions.pop(session.session_id, None)

    def cancel(self, handle: ProviderHandle, session: ProviderSession) -> ProviderResult:
        runtime = self._sessions.pop(session.session_id, None)
        if runtime is not None:
            self._terminate(runtime.process)
        return ProviderResult(TaskState.CANCELLED)

    def stop(self, handle: ProviderHandle) -> ProviderResult:
        for session_id, runtime in tuple(self._sessions.items()):
            if runtime.handle_id == handle.handle_id:
                self._terminate(runtime.process); self._sessions.pop(session_id, None)
        self._live.pop(handle.handle_id, None)
        return ProviderResult(TaskState.SUCCEEDED)
