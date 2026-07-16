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


class ProviderCleanupPending(OpenCodeError):
    def __init__(self, handle: ProviderHandle):
        super().__init__("opencode cleanup is pending")
        self.handle = handle


class ProviderCleanupUnrecoverable(OpenCodeError):
    pass


class _MalformedSseEvent(Exception):
    pass


class LifecycleReasonCode(str, Enum):
    OPENCODE_ERROR = "OPENCODE_ERROR"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_NETWORK = "PROVIDER_NETWORK"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    ABORT_FAILED = "ABORT_FAILED"
    STOP_UNCONFIRMED = "STOP_UNCONFIRMED"


SUPPORTED_OPENCODE_VERSION = "1.15.11"


def _run_version(argv: list[str]) -> str:
    completed = subprocess.run(
        argv, check=True, capture_output=True, text=True, timeout=5,
        env={key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ},
    )
    return completed.stdout


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
            for line in response.iter_lines(chunk_size=1, decode_unicode=True):
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
                 group_members=linux_process_group_members,
                 version_runner: Callable[[list[str]], str] | None = None):
        self.executable, self.transport, self.popen = executable, transport or RequestsTransport(), popen
        self.port_factory, self.password_factory, self.clock = port_factory, password_factory, clock
        self.monotonic, self.sleep, self.killpg, self.getpgid = monotonic, sleep, killpg, getpgid
        self.process_start_token, self.process_uid = process_start_token, process_uid
        self.process_session_id, self.process_executable = process_session_id, process_executable
        self.group_members = group_members
        self.version_runner = version_runner or _run_version
        self._live = {}
        self._tasks: dict[str, _TaskRuntime] = {}

    def probe(self) -> ProviderProbe:
        path, version, reason = self._supported_executable()
        if path is None or version is None:
            return ProviderProbe(False, None, reason)
        return ProviderProbe(True, ProviderCapability("opencode", version), None)

    def _supported_executable(self) -> tuple[str | None, str | None, str | None]:
        path = shutil.which(self.executable)
        if path is None:
            return None, None, "OPENCODE_NOT_FOUND"
        try:
            version = self.version_runner([path, "--version"]).strip()
        except (OSError, subprocess.SubprocessError, ValueError):
            return None, None, "OPENCODE_PROBE_FAILED"
        if version != SUPPORTED_OPENCODE_VERSION:
            return None, None, "OPENCODE_VERSION_UNSUPPORTED"
        return path, version, None

    def _environment(self, runtime: ModelRuntimeConfig, password: str, config_dir: Path) -> dict[str, str]:
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
        isolated_home = config_dir / "home"
        isolated_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        isolated_home.chmod(0o700)
        env["HOME"] = str(isolated_home)
        for name in runtime.credential_env_names:
            if name not in os.environ: raise OpenCodeError(f"required credential variable {name} is unset")
            env[name] = os.environ[name]
        env.update({"OPENCODE_SERVER_USERNAME": "opencode", "OPENCODE_SERVER_PASSWORD": password,
                    "OPENCODE_CONFIG_DIR": str(config_dir), "OPENCODE_DISABLE_AUTOUPDATE": "true",
                    "OPENCODE_DISABLE_LSP_DOWNLOAD": "true", "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true",
                    "OPENCODE_DISABLE_MODELS_FETCH": "true",
                    "NO_PROXY": "localhost,127.0.0.1"})
        return env

    def _safe_source_config(self, spec: ProviderStartSpec) -> dict[str, object]:
        if spec.source_config_path is None:
            return {}
        if spec.source_config_path.resolve() == (spec.config_dir / "opencode.json").resolve():
            raise OpenCodeError("user config must be isolated from generated config")
        try:
            value = json.loads(spec.source_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpenCodeError("user config is unavailable or invalid") from exc
        if not isinstance(value, dict):
            raise OpenCodeError("user config must be a JSON object")
        if set(value) - {"theme", "keybinds"}:
            raise OpenCodeError("user config contains unsupported or conflicting fields")
        theme = value.get("theme")
        if theme is not None and (not isinstance(theme, str) or not theme.strip()):
            raise OpenCodeError("user config theme is invalid")
        keybinds = value.get("keybinds")
        if keybinds is not None and (
            not isinstance(keybinds, dict) or
            any(not isinstance(key, str) or not isinstance(binding, str)
                for key, binding in keybinds.items())
        ):
            raise OpenCodeError("user config keybinds are invalid")
        return dict(value)

    def start(self, spec: ProviderStartSpec) -> ProviderHandle:
        executable_path, _, _ = self._supported_executable()
        if executable_path is None:
            raise OpenCodeError("opencode executable is unavailable or incompatible")
        spec.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        spec.config_dir.chmod(0o700)
        config = {**self._safe_source_config(spec),
                  "autoupdate": False, "share": "disabled", "model": f"{spec.runtime.provider}/{spec.runtime.model}",
                  "provider": {spec.runtime.provider: {"env": list(spec.runtime.credential_env_names),
                  "options": {"baseURL": spec.runtime.endpoint}}}}
        path = spec.config_dir / "opencode.json"
        temporary = spec.config_dir / f".opencode.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        port, password = self.port_factory(), self.password_factory()
        argv = [executable_path, "serve", "--hostname", "127.0.0.1", "--port", str(port)]
        process = self.popen(argv, cwd=str(spec.workspace), env=self._environment(spec.runtime, password, spec.config_dir),
                             text=True, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base_url, deadline = f"http://127.0.0.1:{port}", self.monotonic() + spec.startup_timeout_seconds
        pgid = process.pid; candidate = None
        provisional_handle = ProviderHandle(
            uuid.uuid4().hex, "opencode", "unknown", base_url, process.pid,
        )
        try:
            pgid = self.getpgid(process.pid)
            start_token = self.process_start_token(process.pid)
            uid = self.process_uid(process.pid)
            sid = self.process_session_id(process.pid)
            executable = self.process_executable(process.pid)
            candidate = _Live(
                process, password, spec, pgid, start_token, uid, sid, executable,
            )
            self._live[provisional_handle.handle_id] = candidate
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
                if version.strip() != SUPPORTED_OPENCODE_VERSION:
                    raise OpenCodeError("unsupported opencode version")
                handle = ProviderHandle(
                    provisional_handle.handle_id, "opencode", version.strip(), base_url, process.pid,
                )
                return handle
        except BaseException as original_error:
            cleanup_error = None
            try:
                if candidate is None:
                    self._terminate_unverified_group(
                        process, pgid, spec.shutdown_timeout_seconds,
                    )
                else:
                    self._terminate_owned_group(candidate)
            except BaseException as exc:
                cleanup_error = exc
            if candidate is None:
                password = ""
                if cleanup_error is not None:
                    raise ProviderCleanupUnrecoverable(
                        "opencode cleanup could not be confirmed without a complete identity"
                    ) from original_error
                raise
            candidate.password = ""
            password = ""
            if cleanup_error is not None:
                raise ProviderCleanupPending(provisional_handle) from original_error
            self._live.pop(provisional_handle.handle_id, None)
            raise

    def _unverified_group_is_empty(self, pgid: int) -> bool:
        try:
            return not tuple(self.group_members(pgid))
        except (OSError, TypeError):
            return False

    def _terminate_unverified_group(
        self, process: ManagedProcess, pgid: int, timeout: float,
    ) -> None:
        if self._unverified_group_is_empty(pgid):
            return
        try:
            self.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            if self._unverified_group_is_empty(pgid):
                return
        if process.poll() is None:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
        if self._unverified_group_is_empty(pgid):
            return
        try:
            self.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            if self._unverified_group_is_empty(pgid):
                return
        if process.poll() is None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if not self._unverified_group_is_empty(pgid):
            raise ProviderCleanupUnrecoverable(
                "opencode process group exit was not confirmed"
            )

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
        try:
            self.killpg(live.pgid, signal.SIGTERM)
        except ProcessLookupError as exc:
            members = self._confirmed_owned_group(live)
            if members == ():
                return
            raise OpenCodeError("opencode process group exit was not confirmed") from exc
        if live.process.poll() is None:
            try:
                live.process.wait(timeout=live.spec.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                pass
        members = self._confirmed_owned_group(live)
        if members is None:
            raise OpenCodeError("opencode process group ownership changed")
        if not members:
            return
        if self._wait_owned_group_gone(live, live.spec.shutdown_timeout_seconds):
            return
        members = self._confirmed_owned_group(live)
        if members is None:
            raise OpenCodeError("opencode process group ownership changed")
        if not members:
            return
        try:
            self.killpg(live.pgid, signal.SIGKILL)
        except ProcessLookupError as exc:
            members = self._confirmed_owned_group(live)
            if members == ():
                return
            raise OpenCodeError("opencode process group exit was not confirmed") from exc
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

    def resume_session(
        self,
        handle: ProviderHandle,
        *,
        task_id: str,
        session_id: str,
        timeout_seconds: float = 900.0,
    ) -> ProviderSession:
        """Resume the event stream for an existing OpenCode session without resubmitting its prompt."""
        if handle.handle_id not in self._live or not task_id or not session_id or timeout_seconds <= 0:
            raise OpenCodeError("OpenCode session resume parameters are invalid")
        session = ProviderSession(task_id, session_id, handle.handle_id)
        self._tasks.setdefault(session_id, _TaskRuntime(handle.handle_id, timeout_seconds))
        return session

    def _event(self, handle, session, kind, state, sequence, details=None):
        values = {"sequence": sequence}; values.update(details or {})
        return TaskEvent(session.task_id, session.session_id, "opencode", handle.provider_version, 1, 1,
                         self.clock(), kind, state, values)

    @staticmethod
    def _event_text(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise _MalformedSseEvent()
        return value

    def _failed_events(self, handle, session, sequence, reason_code):
        sequence += 1
        yield self._event(
            handle, session, EventType.TASK_BLOCKED, TaskState.BLOCKED, sequence,
            {"reason_code": reason_code.value},
        )
        sequence += 1
        yield self._event(
            handle, session, EventType.TASK_FINISHED, TaskState.FAILED, sequence,
            {"reason_code": reason_code.value},
        )

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
                if not isinstance(kind, str):
                    raise _MalformedSseEvent()
                if kind == "todo.updated":
                    todos = props.get("todos")
                    if not isinstance(todos, list):
                        raise _MalformedSseEvent()
                    yield self._event(handle, session, EventType.PLAN_READY, TaskState.RUNNING, sequence, {"test_count": len(todos)})
                elif kind == "permission.asked":
                    yield self._event(handle, session, EventType.TOOL_REQUESTED, TaskState.AWAITING_APPROVAL, sequence,
                                      {"tool_name": self._event_text(props.get("permission")),
                                       "tool_call_id": self._event_text(props.get("id"))})
                elif kind == "message.part.updated":
                    part = props.get("part")
                    if not isinstance(part, dict):
                        raise _MalformedSseEvent()
                    state = part.get("state")
                    if not isinstance(state, dict):
                        raise _MalformedSseEvent()
                    tool = self._event_text(part.get("tool"))
                    call_id = self._event_text(part.get("callID"))
                    status = self._event_text(state.get("status"))
                    metadata = state.get("metadata", {})
                    if not isinstance(metadata, dict):
                        raise _MalformedSseEvent()
                    exit_code = metadata.get("exit", 0)
                    if type(exit_code) is not int:
                        raise _MalformedSseEvent()
                    event_type = EventType.TEST_COMPLETED if tool == "test" and status == "completed" else (
                        EventType.TOOL_COMPLETED if status == "completed" else EventType.TOOL_REQUESTED
                    )
                    event_state = TaskState.RUNNING if status == "completed" else TaskState.AWAITING_APPROVAL
                    yield self._event(handle, session, event_type, event_state, sequence,
                                      {"tool_name": tool, "tool_call_id": call_id, "exit_code": exit_code})
                elif kind == "session.diff":
                    diff = props.get("diff")
                    if not isinstance(diff, list):
                        raise _MalformedSseEvent()
                    yield self._event(handle, session, EventType.ARTIFACT_CREATED, TaskState.RUNNING, sequence,
                                      {"artifact_count": len(diff)})
                elif kind == "session.error":
                    yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.FAILED, sequence,
                                      {"reason_code": LifecycleReasonCode.OPENCODE_ERROR.value})
                    return
                elif kind == "session.idle":
                    yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.SUCCEEDED, sequence, {"result_state": "succeeded"})
                    return
            self._abort_quietly(handle, session, live)
            yield from self._failed_events(
                handle, session, sequence, LifecycleReasonCode.PROVIDER_TIMEOUT,
            )
        except _MalformedSseEvent:
            self._abort_quietly(handle, session, live)
            yield from self._failed_events(
                handle, session, sequence, LifecycleReasonCode.OPENCODE_ERROR,
            )
        except (requests.RequestException, ValueError):
            self._abort_quietly(handle, session, live)
            yield from self._failed_events(
                handle, session, sequence, LifecycleReasonCode.PROVIDER_NETWORK,
            )
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
