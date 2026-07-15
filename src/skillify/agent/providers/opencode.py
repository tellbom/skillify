from __future__ import annotations

import base64, json, os, secrets, shutil, signal, socket, subprocess, time, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, Mapping, Protocol

import requests

from skillify.agent.events import EventType, TaskEvent, TaskState
from skillify.agent.provider import (
    ModelRuntimeConfig, ProviderCapability, ProviderHandle, ProviderProbe,
    ProviderResult, ProviderSession, ProviderStartSpec, TaskSpec,
)


class OpenCodeError(Exception): pass
class ProviderCrashed(OpenCodeError): pass
class ProviderTimeout(OpenCodeError): pass


class LifecycleReasonCode(str, Enum):
    OPENCODE_ERROR = "OPENCODE_ERROR"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_NETWORK = "PROVIDER_NETWORK"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    ABORT_FAILED = "ABORT_FAILED"
    STOP_UNCONFIRMED = "STOP_UNCONFIRMED"


class ManagedProcess(Protocol):
    pid: int
    def poll(self) -> int | None: """Return the process status."""
    def wait(self, timeout: float | None = None) -> int: """Wait for termination."""


class HttpTransport(Protocol):
    def request_json(self, method: str, url: str, *, password: str, timeout: float,
                     body: Mapping[str, object] | None = None) -> Mapping[str, object]: """Perform one JSON request."""
    def iter_sse(self, url: str, *, password: str, timeout: float) -> Iterator[Mapping[str, object]]: """Yield decoded SSE data objects."""


def _auth(password: str) -> str:
    token = base64.b64encode(f"opencode:{password}".encode()).decode()
    return f"Basic {token}"


class RequestsTransport:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.trust_env = False

    def request_json(self, method, url, *, password, timeout, body=None):
        response = self.session.request(method, url, headers={"Authorization": _auth(password)}, json=body, timeout=timeout)
        response.raise_for_status()
        return {} if response.status_code == 204 else response.json()
    def iter_sse(self, url, *, password, timeout):
        with self.session.get(url, headers={"Authorization": _auth(password)}, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if line and line.startswith("data: "):
                    value = json.loads(line[6:])
                    if isinstance(value, dict): yield value
                elif not line or line.startswith(":"):
                    yield {}


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def linux_process_start_token(pid: int) -> str:
    return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]


def linux_process_uid(pid: int) -> int:
    return Path(f"/proc/{pid}").stat().st_uid


def linux_process_session_id(pid: int) -> int:
    return os.getsid(pid)


def linux_process_executable(pid: int) -> str:
    return str(Path(os.readlink(f"/proc/{pid}/exe")).resolve(strict=True))


@dataclass(frozen=True)
class ProcessGroupMember:
    pid: int
    pgid: int
    sid: int
    uid: int
    start_token: str


def linux_process_group_members(pgid: int) -> tuple[ProcessGroupMember, ...]:
    members = []
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            raw = (proc_dir / "stat").read_text(encoding="utf-8")
            prefix, separator, suffix = raw.rpartition(") ")
            if not separator:
                continue
            fields = suffix.split()
            member_pgid, sid = int(fields[2]), int(fields[3])
            if member_pgid == pgid:
                members.append(ProcessGroupMember(
                    pid=int(prefix.split(" ", 1)[0]), pgid=member_pgid, sid=sid,
                    uid=proc_dir.stat().st_uid, start_token=fields[19],
                ))
        except (OSError, ValueError, IndexError):
            continue
    return tuple(sorted(members, key=lambda member: member.pid))


@dataclass
class _Live:
    process: ManagedProcess
    password: str
    spec: ProviderStartSpec
    pgid: int
    start_token: str
    uid: int
    sid: int
    executable: str


@dataclass(frozen=True)
class _TaskRuntime:
    handle_id: str
    timeout_seconds: float


class OpenCodeProvider:
    def __init__(self, *, executable="opencode", transport=None, popen=subprocess.Popen,
                 port_factory: Callable[[], int] = find_free_port,
                 password_factory=lambda: secrets.token_urlsafe(32),
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 monotonic=time.monotonic, sleep=time.sleep,
                 killpg=os.killpg, getpgid=os.getpgid, process_start_token=linux_process_start_token,
                 process_uid=linux_process_uid, process_session_id=linux_process_session_id,
                 process_executable=linux_process_executable,
                 group_members=linux_process_group_members):
        self.executable, self.transport, self.popen = executable, transport or RequestsTransport(), popen
        self.port_factory, self.password_factory, self.clock = port_factory, password_factory, clock
        self.monotonic, self.sleep, self.killpg, self.getpgid = monotonic, sleep, killpg, getpgid
        self.process_start_token, self.process_uid = process_start_token, process_uid
        self.process_session_id, self.process_executable = process_session_id, process_executable
        self.group_members = group_members
        self._live = {}
        self._tasks: dict[str, _TaskRuntime] = {}

    def probe(self) -> ProviderProbe:
        path = shutil.which(self.executable)
        return ProviderProbe(bool(path), ProviderCapability("opencode", "1.15.11") if path else None,
                             None if path else "OPENCODE_NOT_FOUND")

    def _environment(self, runtime: ModelRuntimeConfig, password: str, config_dir: Path) -> dict[str, str]:
        env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL") if key in os.environ}
        for name in runtime.credential_env_names:
            if name not in os.environ: raise OpenCodeError(f"required credential variable {name} is unset")
            env[name] = os.environ[name]
        env.update({"OPENCODE_SERVER_USERNAME": "opencode", "OPENCODE_SERVER_PASSWORD": password,
                    "OPENCODE_CONFIG_DIR": str(config_dir), "OPENCODE_DISABLE_AUTOUPDATE": "true",
                    "OPENCODE_DISABLE_LSP_DOWNLOAD": "true", "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true",
                    "NO_PROXY": "localhost,127.0.0.1"})
        return env

    def start(self, spec: ProviderStartSpec) -> ProviderHandle:
        spec.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        config = {"autoupdate": False, "share": "disabled", "model": f"{spec.runtime.provider}/{spec.runtime.model}",
                  "provider": {spec.runtime.provider: {"env": list(spec.runtime.credential_env_names),
                  "options": {"baseURL": spec.runtime.endpoint}}}}
        path = spec.config_dir / "opencode.json"; path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8"); path.chmod(0o600)
        port, password = self.port_factory(), self.password_factory()
        argv = [self.executable, "serve", "--hostname", "127.0.0.1", "--port", str(port)]
        process = self.popen(argv, cwd=str(spec.workspace), env=self._environment(spec.runtime, password, spec.config_dir),
                             text=True, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base_url, deadline = f"http://127.0.0.1:{port}", self.monotonic() + spec.startup_timeout_seconds
        pgid = process.pid; candidate = None
        try:
            pgid = self.getpgid(process.pid)
            start_token = self.process_start_token(process.pid)
            uid = self.process_uid(process.pid)
            sid = self.process_session_id(process.pid)
            executable = self.process_executable(process.pid)
            candidate = _Live(
                process, password, spec, pgid, start_token, uid, sid, executable,
            )
            while True:
                if process.poll() is not None: raise ProviderCrashed("opencode exited during startup")
                if self.monotonic() >= deadline: raise ProviderTimeout("opencode startup timed out")
                try:
                    health = self.transport.request_json(
                        "GET", base_url + "/global/health", password=password, timeout=0.5,
                    )
                except requests.RequestException:
                    self.sleep(0.05)
                    continue
                if health.get("healthy") is not True:
                    self.sleep(0.05)
                    continue
                version = health.get("version")
                if not isinstance(version, str) or not version.strip():
                    raise OpenCodeError("opencode health response omitted version")
                handle = ProviderHandle(uuid.uuid4().hex, "opencode", version, base_url, process.pid)
                self._live[handle.handle_id] = candidate
                return handle
        except BaseException:
            try:
                if candidate is None:
                    self._terminate(process, pgid, spec.shutdown_timeout_seconds)
                else:
                    self._terminate_owned_group(candidate)
            except Exception:
                pass
            finally:
                password = ""
            raise

    def _terminate(self, process: ManagedProcess, pgid: int, timeout: float) -> None:
        if process.poll() is not None: return
        self.killpg(pgid, signal.SIGTERM)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.killpg(pgid, signal.SIGKILL)
            process.wait(timeout=1)

    def _owned_group_snapshot(self, live: _Live):
        try:
            leader_start = int(live.start_token)
            members = tuple(self.group_members(live.pgid))
        except (OSError, TypeError, ValueError):
            return None
        leader_alive = live.process.poll() is None
        if not members:
            return None if leader_alive else ()
        leader_seen = False
        for member in members:
            try:
                if (member.pgid != live.pgid or member.sid != live.sid or
                        member.uid != live.uid or int(member.start_token) < leader_start):
                    return None
                if member.pid == live.process.pid:
                    leader_seen = True
                    if member.start_token != live.start_token:
                        return None
            except (AttributeError, TypeError, ValueError):
                return None
        if leader_alive and not leader_seen:
            return None
        return members

    def _confirmed_owned_group(self, live: _Live):
        first = self._owned_group_snapshot(live)
        if first is None or not first:
            return first
        return self._owned_group_snapshot(live)

    def _wait_owned_group_gone(self, live: _Live, timeout: float) -> bool:
        deadline = self.monotonic() + timeout
        while True:
            members = self._owned_group_snapshot(live)
            if members == ():
                return True
            if members is None or self.monotonic() >= deadline:
                return False
            self.sleep(0.05)

    def _terminate_owned_group(self, live: _Live) -> None:
        members = self._confirmed_owned_group(live)
        if members is None:
            raise OpenCodeError("opencode process group ownership changed")
        if not members:
            return
        self.killpg(live.pgid, signal.SIGTERM)
        if live.process.poll() is None:
            try:
                live.process.wait(timeout=live.spec.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                pass
        if self._wait_owned_group_gone(live, live.spec.shutdown_timeout_seconds):
            return
        members = self._confirmed_owned_group(live)
        if members is None:
            raise OpenCodeError("opencode process group ownership changed")
        if not members:
            return
        self.killpg(live.pgid, signal.SIGKILL)
        if live.process.poll() is None:
            try:
                live.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if not self._wait_owned_group_gone(live, 1):
            raise ProviderTimeout("opencode process group exit was not confirmed")

    def _abort_quietly(self, handle: ProviderHandle, session: ProviderSession, live: _Live) -> None:
        try:
            self.transport.request_json("POST", handle.base_url + f"/session/{session.session_id}/abort",
                                        password=live.password, timeout=1)
        except Exception:
            pass

    def create_session(self, handle: ProviderHandle, spec: TaskSpec) -> ProviderSession:
        live = self._live[handle.handle_id]
        raw = self.transport.request_json("POST", handle.base_url + "/session", password=live.password, timeout=5,
                                          body={"title": f"skillify:{spec.task_id}"})
        session = ProviderSession(spec.task_id, str(raw["id"]), handle.handle_id)
        self.transport.request_json("POST", handle.base_url + f"/session/{session.session_id}/prompt_async",
                                    password=live.password, timeout=5, body={"parts": [{"type": "text", "text": spec.prompt}]})
        self._tasks[session.session_id] = _TaskRuntime(handle.handle_id, spec.timeout_seconds)
        return session

    def _event(self, handle, session, kind, state, sequence, details=None):
        values = {"sequence": sequence}; values.update(details or {})
        return TaskEvent(session.task_id, session.session_id, "opencode", handle.provider_version, 1, 1,
                         self.clock(), kind, state, values)

    def stream_events(self, handle, session):
        live = self._live[handle.handle_id]
        if live.process.poll() is not None: raise ProviderCrashed("opencode exited")
        task = self._tasks[session.session_id]; deadline = self.monotonic() + task.timeout_seconds
        sequence = 1
        try:
            yield self._event(handle, session, EventType.TASK_ACCEPTED, TaskState.QUEUED, sequence)
            for raw in self.transport.iter_sse(handle.base_url + "/event", password=live.password, timeout=task.timeout_seconds):
                if live.process.poll() is not None: raise ProviderCrashed("opencode exited")
                if self.monotonic() >= deadline: break
                props = raw.get("properties", {})
                if not isinstance(props, dict) or props.get("sessionID") != session.session_id: continue
                sequence += 1; kind = raw.get("type")
                if kind == "todo.updated":
                    yield self._event(handle, session, EventType.PLAN_READY, TaskState.RUNNING, sequence, {"test_count": len(props.get("todos", []))})
                elif kind == "permission.asked":
                    yield self._event(handle, session, EventType.TOOL_REQUESTED, TaskState.AWAITING_APPROVAL, sequence,
                                      {"tool_name": str(props.get("permission", "unknown")), "tool_call_id": str(props.get("id", "unknown"))})
                elif kind == "message.part.updated":
                    part = props.get("part", {}); state = part.get("state", {}) if isinstance(part, dict) else {}
                    tool = str(part.get("tool", "unknown")) if isinstance(part, dict) else "unknown"
                    call_id = str(part.get("callID", "unknown")) if isinstance(part, dict) else "unknown"
                    status = state.get("status") if isinstance(state, dict) else None
                    metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
                    exit_code = metadata.get("exit", 0) if isinstance(metadata, dict) else 0
                    event_type = EventType.TEST_COMPLETED if tool == "test" and status == "completed" else (
                        EventType.TOOL_COMPLETED if status == "completed" else EventType.TOOL_REQUESTED
                    )
                    event_state = TaskState.RUNNING if status == "completed" else TaskState.AWAITING_APPROVAL
                    yield self._event(handle, session, event_type, event_state, sequence,
                                      {"tool_name": tool, "tool_call_id": call_id, "exit_code": int(exit_code)})
                elif kind == "session.diff":
                    yield self._event(handle, session, EventType.ARTIFACT_CREATED, TaskState.RUNNING, sequence,
                                      {"artifact_count": len(props.get("diff", []))})
                elif kind == "session.error":
                    yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.FAILED, sequence,
                                      {"reason_code": LifecycleReasonCode.OPENCODE_ERROR.value})
                    return
                elif kind == "session.idle":
                    yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.SUCCEEDED, sequence, {"result_state": "succeeded"})
                    return
            self._abort_quietly(handle, session, live)
            sequence += 1
            yield self._event(handle, session, EventType.TASK_BLOCKED, TaskState.BLOCKED, sequence,
                              {"reason_code": LifecycleReasonCode.PROVIDER_TIMEOUT.value})
            sequence += 1
            yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.FAILED, sequence,
                              {"reason_code": LifecycleReasonCode.PROVIDER_TIMEOUT.value})
        except (requests.RequestException, ValueError):
            self._abort_quietly(handle, session, live)
            sequence += 1
            yield self._event(handle, session, EventType.TASK_BLOCKED, TaskState.BLOCKED, sequence,
                              {"reason_code": LifecycleReasonCode.PROVIDER_NETWORK.value})
            sequence += 1
            yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.FAILED, sequence,
                              {"reason_code": LifecycleReasonCode.PROVIDER_NETWORK.value})
        finally:
            self._tasks.pop(session.session_id, None)

    def cancel(self, handle, session):
        live = self._live[handle.handle_id]
        try:
            self.transport.request_json("POST", handle.base_url + f"/session/{session.session_id}/abort",
                                        password=live.password, timeout=5)
        finally:
            self._tasks.pop(session.session_id, None)
        return ProviderResult(TaskState.CANCELLED)

    def stop(self, handle):
        live = self._live.get(handle.handle_id)
        if live is None: return ProviderResult(TaskState.SUCCEEDED)
        try: self.transport.request_json("POST", handle.base_url + "/instance/dispose", password=live.password, timeout=1)
        except Exception: pass
        self._terminate_owned_group(live)
        self._live.pop(handle.handle_id, None)
        live.password = ""
        for session_id, task in tuple(self._tasks.items()):
            if task.handle_id == handle.handle_id: self._tasks.pop(session_id, None)
        return ProviderResult(TaskState.SUCCEEDED)

    def ownership(self, handle):
        live = self._live[handle.handle_id]
        return {"pid": handle.process_id, "pgid": live.pgid, "sid": live.sid,
                "start_token": live.start_token, "uid": live.uid, "executable": live.executable}
