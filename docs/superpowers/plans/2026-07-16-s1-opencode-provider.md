# S1 OpenCode Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `skillctl` with a local, offline-testable endpoint-agent command group, a versioned Provider contract, an OpenCode Server adapter, and a checksum-locked offline distribution path.

**Architecture:** Keep Python `skillctl` as the only CLI and put executor-specific behavior behind a synchronous `AgentProvider` Protocol. The OpenCode adapter starts a localhost-only process and uses the official HTTP/OpenAPI/SSE interface through the repository's existing `requests` dependency; deterministic fakes replace process, HTTP, clock, randomness, platform, and filesystem boundaries in default tests. A pinned manifest governs offline binaries, while all real Linux/OpenCode/model/MCP acceptance remains `[test-env]`.

**Tech Stack:** Python 3.10+, Typer, Rich, dataclasses, `requests`, PyYAML, jsonschema, pytest, stdlib subprocess/socket/secrets/tempfile; OpenCode Server/OpenAPI v1.15.11.

## Global Constraints

- Extend the existing `skillctl`; do not add an overlapping CLI or change its implementation language.
- OpenCode first; do not implement a Claude Code Provider before G1 `[test-env]` passes.
- Do not rewrite OpenCode's agent loop or native file/Shell/Git/test tools, and do not force all local tools through MCP.
- Execution is local, the server is control plane only, endpoint connectivity is outbound, and the server must not access local paths or listen on endpoint inbound ports.
- OpenCode Server binds only `127.0.0.1`, disables mDNS, uses a random free port and a temporary strong Basic Auth password, and receives bounded startup/request/task/shutdown timeouts.
- Default telemetry and Provider events exclude prompt, source code, secrets, environment variables, database results, raw tool input, and raw tool output.
- Workspaces and allowed paths are explicit; never scan the whole machine by default.
- External interactions are dependency-injected and replaceable by fakes; filesystem uses temporary directories, DB logic uses SQLite/temporary DB, and time/random/process/network are injectable where relevant.
- New OSS records version, license, source, checksum, and intranet mirror/offline strategy; runtime never implicitly accesses the public internet.
- Preserve Forgejo immutable artifacts, checksum validation, per-Skill `uv` venv, and devpi dependency flow.
- `task_protocol_version: 1` and `provider_contract_version: 1`.
- Real OpenCode/model/MCP/Linux checks use `pytest.mark.skip(reason="requires test-env: real OpenCode binary, model endpoint, MCP runtime, and target Linux")` by default.
- Existing backend and frontend failures recorded in the repository assessment are baseline debt and must not be attributed to S1.

## Baseline Commands

The exact macOS sync is blocked by the existing DM wheels. Use these focused commands during S1:

```bash
uv sync --no-install-package dmpython --no-install-package dmsqlalchemy
uv run --no-sync python -m compileall -q src
uv run --no-sync pytest tests/test_cli_agent.py tests/test_provider_contract.py tests/test_opencode_provider_contract.py tests/test_opencode_provider_smoke.py tests/test_opencode_distribution.py -q
```

At the final S1 gate, also run the full fallback backend suite and compare with the recorded `319 passed, 1 failed, 1 skipped`; no new failure is allowed. S1 does not modify `web/`, but final regression evidence includes `npm run type-check`, `npm test`, and `npm run build` with the existing footer failure identified separately.

---

### Task 1.1: CLI Command Surface and XDG Paths

**Files:**
- Modify: `src/skillify/cli/main.py`
- Modify: `src/skillify/common/config.py`
- Create: `src/skillify/cli/agent_cmd.py`
- Test: `tests/test_cli_agent.py`

**Interfaces:**
- Consumes: existing `skillify.cli.main.app`, Rich `console`/`err_console`, PyYAML, and Typer `CliRunner` conventions.
- Produces: `AgentPaths`, `AgentLocalConfig`, `load_agent_paths()`, `load_agent_local_config()`, `save_agent_local_config()`, `agent_app`, stable `AgentErrorCode` strings, and exit-code behavior used by Tasks 1.2–1.4.

Use these exact configuration types and names:

```python
@dataclass(frozen=True)
class AgentPaths:
    config_dir: Path
    state_dir: Path
    cache_dir: Path
    log_dir: Path

    @property
    def config_path(self) -> Path: return self.config_dir / "config.yaml"
    @property
    def runtime_path(self) -> Path: return self.state_dir / "runtime.json"
    @property
    def log_path(self) -> Path: return self.log_dir / "agent.log"

@dataclass(frozen=True)
class AgentLocalConfig:
    provider: str = "opencode"
    allowed_workspaces: tuple[str, ...] = ()
    opencode_manifest_path: str | None = None
    opencode_artifact_root: str | None = None

def load_agent_paths(
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> AgentPaths:
    env = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    config_home = Path(env.get("XDG_CONFIG_HOME", user_home / ".config"))
    state_home = Path(env.get("XDG_STATE_HOME", user_home / ".local" / "state"))
    cache_home = Path(env.get("XDG_CACHE_HOME", user_home / ".cache"))
    return AgentPaths(
        config_dir=Path(env.get("SKILLIFY_AGENT_CONFIG_DIR", config_home / "skillify" / "agent")),
        state_dir=Path(env.get("SKILLIFY_AGENT_STATE_DIR", state_home / "skillify" / "agent")),
        cache_dir=Path(env.get("SKILLIFY_AGENT_CACHE_DIR", cache_home / "skillify" / "agent")),
        log_dir=Path(env.get("SKILLIFY_AGENT_LOG_DIR", state_home / "skillify" / "agent" / "log")),
    )

def load_agent_local_config(paths: AgentPaths) -> AgentLocalConfig:
    if not paths.config_path.is_file():
        return AgentLocalConfig()
    data = yaml.safe_load(paths.config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("agent config must be a mapping")
    return AgentLocalConfig(
        provider=str(data.get("provider", "opencode")),
        allowed_workspaces=tuple(data.get("allowed_workspaces", ())),
        opencode_manifest_path=data.get("opencode_manifest_path"),
        opencode_artifact_root=data.get("opencode_artifact_root"),
    )

def save_agent_local_config(paths: AgentPaths, config: AgentLocalConfig) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = paths.config_path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(asdict(config), sort_keys=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(paths.config_path)
```

`load_agent_paths()` resolves `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, and `XDG_CACHE_HOME`; defaults are `~/.config`, `~/.local/state`, and `~/.cache`. The config/state/cache roots append `skillify/agent`, and the log root appends `skillify/agent/log` to the state home. `SKILLIFY_AGENT_CONFIG_DIR`, `SKILLIFY_AGENT_STATE_DIR`, `SKILLIFY_AGENT_CACHE_DIR`, and `SKILLIFY_AGENT_LOG_DIR` override them independently.

Stable codes and exits are:

| `AgentErrorCode` value | Exit | Meaning |
| --- | ---: | --- |
| `OK` | 0 | Command succeeded. |
| `AGENT_CONFIG_INVALID` | 10 | Invalid config/XDG state. |
| `AGENT_WORKSPACE_UNAUTHORIZED` | 11 | Workspace is absent from the explicit allowlist or resolves outside it. |
| `AGENT_PROVIDER_UNAVAILABLE` | 12 | OpenCode binary/service is absent. |
| `AGENT_PROVIDER_FAILED` | 13 | Provider start/API/lifecycle failure. |
| `AGENT_TASK_FAILED` | 14 | Accepted task ended failed/blocked. |

- [ ] **Step 1: Write failing XDG and command-surface tests**

Add tests named exactly `test_agent_help_lists_all_subcommands`,
`test_agent_paths_use_separate_xdg_roots`,
`test_agent_init_records_only_resolved_workspace`,
`test_agent_run_rejects_unregistered_workspace`,
`test_agent_doctor_reports_missing_opencode_without_network`,
`test_agent_run_reports_provider_unavailable_without_server`,
`test_agent_status_stop_and_logs_are_local_when_stopped`, and
`test_agent_json_error_envelope_is_stable`.

The help assertion must contain `doctor`, `init`, `run`, `status`, `stop`, and `logs`. The JSON error assertion is exactly:

```python
assert json.loads(result.stdout) == {
    "ok": False,
    "code": "AGENT_WORKSPACE_UNAUTHORIZED",
    "message": "workspace is not registered",
    "data": {},
}
assert result.exit_code == 11
```

- [ ] **Step 2: Run Task 1.1 RED tests**

Run:

```bash
uv run --no-sync pytest tests/test_cli_agent.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'skillify.cli.agent_cmd'` or assertions fail because `agent` is not registered. No network request is permitted.

- [ ] **Step 3: Implement XDG configuration and explicit workspace persistence**

Implement the declarations above in `common/config.py`. YAML is exactly:

```yaml
provider: opencode
allowed_workspaces:
  - /resolved/absolute/workspace
opencode_manifest_path: null
opencode_artifact_root: null
```

Create parent directories with mode `0o700`, write through a sibling temporary file with mode `0o600`, then `replace()` the config. Reject non-mapping YAML, providers other than `opencode`, non-list workspace data, relative workspace values, and duplicate entries after `Path.resolve()`.

- [ ] **Step 4: Implement the six local CLI commands**

Create `agent_app = typer.Typer(name="agent", no_args_is_help=True)`. Every command accepts `--format text|json`; JSON emits the exact envelope `{"ok": bool, "code": str, "message": str, "data": dict}`.

Implement behavior exactly:

- `init --workspace PATH --provider opencode`: require an existing directory; reject `/`, the resolved home directory, and symlink escapes; append one resolved path idempotently.
- `doctor`: read only local config, platform, `shutil.which("opencode")`, manifest presence, and workspace writability; missing services return `AGENT_PROVIDER_UNAVAILABLE` without contacting Skillify.
- `run --workspace PATH --prompt-file PATH`: authorize the resolved workspace first; read prompt only after authorization; before Task 1.3, missing OpenCode returns `AGENT_PROVIDER_UNAVAILABLE` and never starts a server.
- `status`: missing `runtime.json` is successful with `{"state":"stopped"}`.
- `stop`: missing runtime is successful and idempotent.
- `logs --lines N`: read at most the last `N` UTF-8 lines from `AgentPaths.log_path`; missing log returns an empty list.

Do not accept a raw prompt option because shell history is persistent. `--prompt-file -` reads stdin in memory.

- [ ] **Step 5: Register the sub-app and run GREEN tests**

Add to `main.py` after app construction:

```python
from skillify.cli.agent_cmd import agent_app
app.add_typer(agent_app, name="agent")
```

Run:

```bash
uv run --no-sync python -m compileall -q src
uv run --no-sync pytest tests/test_cli_agent.py -q
```

Expected: compileall exits 0 and `8 passed` (parameterization may increase the pass count, but zero failed/skipped is required).

- [ ] **Step 6: Commit Task 1.1**

```bash
git add src/skillify/cli/main.py src/skillify/common/config.py src/skillify/cli/agent_cmd.py tests/test_cli_agent.py
git commit -m "feat(cli): add endpoint agent command group"
```

---

### Task 1.2: Provider Adapter Contract and FakeProvider

**Files:**
- Create: `src/skillify/agent/__init__.py`
- Create: `src/skillify/agent/provider.py`
- Create: `src/skillify/agent/events.py`
- Create: `src/skillify/agent/fake_provider.py`
- Test: `tests/test_provider_contract.py`

**Interfaces:**
- Consumes: `AgentPaths` from Task 1.1 and Python 3.10-compatible `Enum`, dataclasses, `Protocol`, `Iterator`, `Callable`, and timezone-aware `datetime`.
- Produces: the exact contract below, consumed unchanged by OpenCode and CLI integration in Task 1.3.

`events.py` public interface:

```python
PROVIDER_CONTRACT_VERSION = 1

class TaskState(str, Enum):
    QUEUED = "queued"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

class EventType(str, Enum):
    TASK_ACCEPTED = "task.accepted"
    PLAN_READY = "plan.ready"
    TOOL_REQUESTED = "tool.requested"
    TOOL_COMPLETED = "tool.completed"
    TEST_COMPLETED = "test.completed"
    ARTIFACT_CREATED = "artifact.created"
    TASK_BLOCKED = "task.blocked"
    TASK_FINISHED = "task.finished"

JsonScalar = str | int | float | bool | None

@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    session_id: str
    provider: str
    provider_version: str
    contract_version: int
    timestamp: datetime
    type: EventType
    state: TaskState
    details: Mapping[str, JsonScalar] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "contract_version": self.contract_version,
            "timestamp": self.timestamp.isoformat(),
            "type": self.type.value,
            "state": self.state.value,
            "details": dict(self.details),
        }
```

Allowed detail keys are exactly `sequence`, `tool_name`, `tool_call_id`, `exit_code`, `test_count`, `artifact_count`, `reason_code`, and `result_state`. Reject every other key in `__post_init__`; also require UTC-aware timestamps and `contract_version == 1`. This allowlist prevents prompt/source/secret/environment/database/raw input/output fields by construction.

`provider.py` public interface:

```python
@dataclass(frozen=True)
class ProviderCapability:
    provider: str
    provider_version: str
    contract_version: int
    supports_cancel: bool
    supports_streaming: bool

@dataclass(frozen=True)
class ProviderProbe:
    available: bool
    capability: ProviderCapability | None
    reason_code: str | None = None

@dataclass(frozen=True)
class ProviderStartSpec:
    workspace: Path
    allowed_paths: tuple[Path, ...]
    config_dir: Path
    startup_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0

@dataclass(frozen=True)
class ProviderHandle:
    handle_id: str
    provider: str
    provider_version: str
    base_url: str
    process_id: int

@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    prompt: str
    model: str | None = None
    timeout_seconds: float = 900.0

@dataclass(frozen=True)
class ProviderSession:
    task_id: str
    session_id: str
    handle_id: str

@dataclass(frozen=True)
class ProviderResult:
    state: TaskState
    error_code: str | None = None
    message: str = ""

class AgentProvider(Protocol):
    def probe(self) -> ProviderProbe: raise NotImplementedError
    def start(self, spec: ProviderStartSpec) -> ProviderHandle: raise NotImplementedError
    def create_session(self, handle: ProviderHandle, spec: TaskSpec) -> ProviderSession: raise NotImplementedError
    def stream_events(self, handle: ProviderHandle, session: ProviderSession) -> Iterator[TaskEvent]: raise NotImplementedError
    def cancel(self, handle: ProviderHandle, session: ProviderSession) -> ProviderResult: raise NotImplementedError
    def stop(self, handle: ProviderHandle) -> ProviderResult: raise NotImplementedError
```

- [ ] **Step 1: Write the contract tests first**

Add exactly these behavioral tests:
`test_fake_provider_startup_and_ordered_success`,
`test_fake_provider_cancellation_finishes_cancelled`,
`test_fake_provider_abnormal_exit_finishes_failed`,
`test_fake_provider_stop_cleans_handles_and_sessions`,
`test_task_event_rejects_sensitive_or_unknown_details`,
`test_public_event_contains_identity_version_and_utc_timestamp`, and
`test_all_required_states_and_event_values_are_stable`.

The success event order is exactly:

```python
assert [event.type.value for event in events] == [
    "task.accepted",
    "plan.ready",
    "tool.requested",
    "tool.completed",
    "test.completed",
    "artifact.created",
    "task.finished",
]
assert events[-1].state is TaskState.SUCCEEDED
```

- [ ] **Step 2: Run Task 1.2 RED tests**

Run:

```bash
uv run --no-sync pytest tests/test_provider_contract.py -q
```

Expected: import/collection failure because `skillify.agent` does not exist.

- [ ] **Step 3: Implement events and provider types**

Implement the exact declarations above. Validate that start workspaces and allowed paths are absolute and resolved, the workspace is included in allowed paths, IDs are non-empty, timeouts are positive, and successful/cancelled results have no contradictory error code.

- [ ] **Step 4: Implement deterministic FakeProvider**

Constructor and script modes are exact:

```python
class FakeOutcome(str, Enum):
    SUCCEED = "succeed"
    FAIL = "fail"
    BLOCK = "block"

class FakeProvider:
    def __init__(
        self,
        *,
        outcome: FakeOutcome = FakeOutcome.SUCCEED,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        self.outcome = outcome
        self.clock = clock
        self.id_factory = id_factory
        self.handles: dict[str, ProviderHandle] = {}
        self.sessions: dict[str, ProviderSession] = {}
        self.cancelled_session_ids: set[str] = set()
```

`start()` records one live handle; `create_session()` records one queued session; `stream_events()` emits the exact success sequence above or `task.accepted` then `task.blocked`/`task.finished`; `cancel()` changes the session to cancelled and subsequent streaming emits one cancelled `task.finished`; `stop()` removes all sessions owned by the handle. Repeated cancel/stop is idempotent. No event derives details from `TaskSpec.prompt`.

- [ ] **Step 5: Export the contract and run GREEN tests**

Export all public types from `agent/__init__.py`, then run:

```bash
uv run --no-sync python -m compileall -q src
uv run --no-sync pytest tests/test_provider_contract.py -q
```

Expected: compileall exits 0 and `7 passed`, with zero failed/skipped.

- [ ] **Step 6: Commit Task 1.2**

```bash
git add src/skillify/agent tests/test_provider_contract.py
git commit -m "feat(agent): define provider execution contract"
```

---

### Task 1.3: OpenCode Server/OpenAPI Provider

**Files:**
- Create: `src/skillify/agent/providers/__init__.py`
- Create: `src/skillify/agent/providers/opencode.py`
- Modify: `src/skillify/cli/agent_cmd.py`
- Test: `tests/test_opencode_provider_contract.py`
- Test: `tests/test_opencode_provider_smoke.py`

**Interfaces:**
- Consumes: the Task 1.2 `AgentProvider` signatures without renaming, Task 1.1 `AgentPaths`, existing `requests`, official OpenCode endpoints `GET /global/health`, `POST /session`, `POST /session/{id}/prompt_async`, `GET /event`, `POST /session/{id}/abort`, and `POST /instance/dispose`.
- Produces: `OpenCodeProvider`, `OpenCodeError`, `HttpTransport`, `RequestsTransport`, `ManagedProcess`, and `map_opencode_event()`.

Use these exact seams:

```python
class ManagedProcess(Protocol):
    pid: int
    def poll(self) -> int | None: raise NotImplementedError
    def wait(self, timeout: float | None = None) -> int: raise NotImplementedError

class HttpTransport(Protocol):
    def request_json(
        self, method: str, url: str, *, password: str,
        timeout: float, body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]: raise NotImplementedError
    def iter_sse(
        self, url: str, *, password: str, timeout: float,
    ) -> Iterator[Mapping[str, object]]: raise NotImplementedError

def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])

def strong_password() -> str:
    return secrets.token_urlsafe(32)

class OpenCodeProvider:
    def __init__(
        self,
        *,
        executable: str = "opencode",
        transport: HttpTransport | None = None,
        process_factory: Callable[[list[str], Mapping[str, str], Path], ManagedProcess],
        port_factory: Callable[[], int] = find_free_port,
        password_factory: Callable[[], str] = strong_password,
        clock: Callable[[], datetime],
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.executable = executable
        self.transport = transport or RequestsTransport()
        self.process_factory = process_factory
        self.port_factory = port_factory
        self.password_factory = password_factory
        self.clock = clock
        self.monotonic = monotonic
        self.sleep = sleep
        self._private_handles: dict[str, object] = {}
```

`map_opencode_event(raw, *, session, provider_version, clock, sequence)` returns
`TaskEvent | None` and implements the closed mapping table in Step 4; it never
copies an unlisted value from `raw`.

- [ ] **Step 1: Write offline fake HTTP/process contract tests**

Add tests named exactly
`test_start_uses_localhost_random_port_basic_auth_and_isolated_config`,
`test_normal_completion_maps_safe_ordered_events`,
`test_cancel_posts_abort_and_cleans_process_group`,
`test_timeout_blocks_then_fails_and_cleans_up`,
`test_process_crash_fails_without_waiting_for_network`,
`test_sigterm_path_stops_process_group_and_is_idempotent`,
`test_password_prompt_environment_and_raw_tool_data_never_persist_or_log`, and
`test_foreign_session_events_are_ignored`.

The fake server records method/path/Auth/body and streams fixed SSE dictionaries. The fake process records argv/env/cwd and process-group signals. No test executes a real `opencode` binary or accesses a non-loopback address.

- [ ] **Step 2: Run Task 1.3 RED contract tests**

Run:

```bash
uv run --no-sync pytest tests/test_opencode_provider_contract.py -q
```

Expected: import failure for `skillify.agent.providers.opencode`.

- [ ] **Step 3: Implement secure process startup and HTTP transport**

Build the launch argv exactly as `[
"opencode", "serve", "--hostname", "127.0.0.1", "--port", str(port)
]`.

The default process factory calls `subprocess.Popen(argv, cwd=str(cwd), env=dict(env), text=True, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)`. Build an allowlisted environment containing only `PATH`, `HOME`, locale variables and configured internal model credential names.

Set `OPENCODE_SERVER_USERNAME` to `opencode`, `OPENCODE_SERVER_PASSWORD` to the
return value of `password_factory()`, `OPENCODE_CONFIG_DIR` to
`str(spec.config_dir)`, `OPENCODE_DISABLE_AUTOUPDATE`,
`OPENCODE_DISABLE_LSP_DOWNLOAD`, and `OPENCODE_DISABLE_DEFAULT_PLUGINS` to
`true`, and `NO_PROXY` to `localhost,127.0.0.1`.

Write only non-secret `opencode.json` with `autoupdate:false`, `share:"disabled"`, and the explicit internal model/provider configuration. Poll `/global/health` until the startup deadline; verify reported version is non-empty. Store passwords only in an in-memory private handle record, never `ProviderHandle`, JSON, config, state, exception text, or logs.

- [ ] **Step 4: Implement session creation, SSE filtering, and safe mapping**

Create a session with title `f"skillify:{spec.task_id}"`, submit the prompt asynchronously, and filter every SSE item by `properties.sessionID == session.session_id` before mapping.

Use this mapping and discard all unlisted raw fields:

| OpenCode event | Standard event/details |
| --- | --- |
| `server.connected` or accepted session | `task.accepted`, `sequence` |
| first `todo.updated` | `plan.ready`, `sequence`, `test_count` = todo count |
| `permission.asked` | `tool.requested`, safe `tool_name`, `tool_call_id` |
| tool-part running/completed | `tool.requested`/`tool.completed`, tool name/call ID/exit code only |
| recognized test tool completion | `test.completed`, exit code/test count only |
| `session.diff` | `artifact.created`, `artifact_count` only; never diff text/path |
| `session.error` | `task.finished` failed, safe error class as `reason_code` |
| `session.idle` | `task.finished` succeeded |

Timeout emits `task.blocked` with `reason_code="PROVIDER_TIMEOUT"`, aborts, then emits failed `task.finished`. User cancellation emits cancelled `task.finished`. Process exit before completion emits failed `task.finished` with `reason_code="PROVIDER_CRASH"`.

- [ ] **Step 5: Implement bounded process-group cleanup and CLI wiring**

On POSIX call `os.killpg(process.pid, signal.SIGTERM)`, wait `shutdown_timeout_seconds`, then `SIGKILL` if still alive. Always close HTTP streams and remove in-memory credentials. Register `atexit` and temporary SIGTERM handling only while a handle is live, restore the previous handler on stop, and make stop idempotent.

In `agent_cmd.py`, build the default Provider only after workspace authorization. Persist only task/session/provider/version/state/process ID/base URL to `runtime.json`; never persist prompt/password/credential environment. `status`, `stop`, and `logs` remain local when no handle exists.

- [ ] **Step 6: Add the default-skipped real smoke test**

The module-level marker is exact:

```python
pytestmark = pytest.mark.skip(reason="requires test-env: real OpenCode binary, model endpoint, and target Linux")
```

The smoke test must assert `probe()`, real session completion in an explicit temporary Git workspace, socket ownership only on `127.0.0.1`, no password/config leakage, and no residual process after stop. It is evidence only when the skip is deliberately removed in the approved test environment.

- [ ] **Step 7: Run Task 1.3 GREEN tests and Dev-DoD**

Run:

```bash
uv run --no-sync python -m compileall -q src
uv run --no-sync pytest tests/test_provider_contract.py tests/test_opencode_provider_contract.py tests/test_opencode_provider_smoke.py -q
```

Expected: compileall exits 0; all offline tests pass; exactly the real smoke module is skipped with `requires test-env:`.

- [ ] **Step 8: Commit Task 1.3**

```bash
git add src/skillify/agent/providers src/skillify/cli/agent_cmd.py tests/test_opencode_provider_contract.py tests/test_opencode_provider_smoke.py
git commit -m "feat(agent): add opencode provider"
```

---

### Task 1.4: Offline Distribution and Compatibility Lock

**Files:**
- Modify: `src/skillify/cli/doctor_cmd.py`
- Modify: `src/skillify/common/config.py`
- Create: `src/skillify/install/opencode_distribution.py`
- Create: `infra/offline/opencode-manifest.json`
- Create: `tests/test_opencode_distribution.py`
- Create: `docs/deployment/offline-opencode.md`

**Interfaces:**
- Consumes: existing `skillify.install.extract.sha256_file`, `CheckResult`, jsonschema, Task 1.1 config paths, and OpenCode v1.15.11 official release digests recorded in the assessment.
- Produces: deterministic manifest validation/selection/verification and doctor compatibility output.

Use this public interface:

```python
class DistributionError(Exception): pass
class ManifestInvalid(DistributionError): pass
class ArtifactNotFound(DistributionError): pass
class ArtifactCorrupt(DistributionError): pass

@dataclass(frozen=True)
class OpenCodeArtifact:
    version: str
    skillctl_version: str
    os: str
    arch: str
    libc: str
    cpu: str
    sha256: str
    license: str
    source_url: str
    intranet_uri: str

```

The public call signatures are
`load_manifest(path: Path) -> Mapping[str, object]`,
`validate_manifest(data: Mapping[str, object]) -> None`,
`select_artifact(data: Mapping[str, object], *, version: str, os_name: str,
arch: str, libc: str, cpu: str) -> OpenCodeArtifact`, and
`verify_artifact(path: Path, artifact: OpenCodeArtifact) -> None`.

- [ ] **Step 1: Write failing manifest/checksum/doctor tests**

Add exactly `test_repository_manifest_matches_schema_and_has_no_latest`,
`test_selects_exact_glibc_x64_baseline_artifact`,
`test_selects_exact_musl_and_arm64_artifacts`,
`test_rejects_floating_version_or_public_runtime_uri`,
`test_verifies_matching_sha256`, `test_rejects_corrupt_package`, and
`test_doctor_reports_manifest_version_platform_and_checksum`.

- [ ] **Step 2: Run Task 1.4 RED tests**

Run:

```bash
uv run --no-sync pytest tests/test_opencode_distribution.py -q
```

Expected: import failure for `skillify.install.opencode_distribution` and missing repository manifest.

- [ ] **Step 3: Implement strict schema, selection, and checksum verification**

Schema version is integer `1`; manifest `opencodeVersion` is exact semver `1.15.11`; `skillctlVersion` is `0.1.0`; every artifact requires all `OpenCodeArtifact` fields; SHA-256 is 64 lowercase hex characters; license is `MIT`; `sourceUrl` must use HTTPS GitHub Release URLs; `intranetUri` must use `file:` or an approved intranet scheme and must not point to GitHub/public hosts. Reject duplicate `(version, os, arch, libc, cpu)` tuples and any string containing `latest`.

Selection is exact, except `cpu="baseline"` may satisfy an x64 host when AVX2 is absent. It never chooses a higher version. `verify_artifact()` compares with `sha256_file()` using `hmac.compare_digest` and raises `ArtifactCorrupt` before extraction.

- [ ] **Step 4: Create the canonical v1.15.11 manifest**

Create six entries for the exact official artifacts and SHA-256 values in the repository assessment. Use these literal bundle locations:

```text
file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64.tar.gz
file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64-baseline.tar.gz
file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64-musl.tar.gz
file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64-baseline-musl.tar.gz
file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-arm64.tar.gz
file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-arm64-musl.tar.gz
```

For each entry, `sourceUrl` is the literal
`https://github.com/anomalyco/opencode/releases/download/v1.15.11/` prefix plus
the file name on the same manifest entry. This records provenance without
permitting runtime public download.

- [ ] **Step 5: Extend doctor and configuration**

Add environment overrides `SKILLIFY_OPENCODE_MANIFEST_PATH` and `SKILLIFY_OPENCODE_ARTIFACT_ROOT`. Doctor detects OS/arch/libc/AVX2 through an injected detector in tests, loads the configured manifest, selects exact v1.15.11, verifies the local artifact if present, compares `opencode --version`, and reports distinct check names:

```text
opencode-manifest
opencode-platform
opencode-version
opencode-checksum
```

An absent artifact is a clear failure with the bundle path; doctor never downloads it. Existing Forgejo/devpi/Skill target checks remain unchanged.

- [ ] **Step 6: Write the offline deployment runbook**

Document exact staging download URL, official and recomputed SHA-256, MIT notice retention, malware/OSS approval, immutable intranet publication, manifest placement, checksum-first extraction, `OPENCODE_DISABLE_AUTOUPDATE`, `OPENCODE_DISABLE_LSP_DOWNLOAD`, internal model config, `NO_PROXY`, rollback, and these `[test-env]` commands:

```bash
opencode --version
skillctl agent doctor --format json
ss -ltnp
ps -ef | grep '[o]pencode serve'
```

Include disconnected install, upgrade, downgrade, localhost binding, task execution, and residual-process evidence. Do not include `curl | sh`.

- [ ] **Step 7: Run Task 1.4 GREEN tests and focused S1 regression**

Run:

```bash
uv run --no-sync python -m compileall -q src
uv run --no-sync pytest tests/test_cli_agent.py tests/test_provider_contract.py tests/test_opencode_provider_contract.py tests/test_opencode_provider_smoke.py tests/test_opencode_distribution.py -q
```

Expected: compileall exits 0; every offline test passes; only `tests/test_opencode_provider_smoke.py` skips for `requires test-env:`.

- [ ] **Step 8: Commit Task 1.4**

```bash
git add src/skillify/cli/doctor_cmd.py src/skillify/common/config.py src/skillify/install/opencode_distribution.py infra/offline/opencode-manifest.json tests/test_opencode_distribution.py docs/deployment/offline-opencode.md
git commit -m "build(agent): add offline opencode distribution"
```

---

## S1 Dev-DoD and G1 Handoff

- [ ] Run fallback compileall; expected exit 0.
- [ ] Run all five focused S1 test modules; expected all offline tests pass and only the real smoke test skips with `requires test-env:`.
- [ ] Run fallback full pytest and compare to the recorded baseline; expected no new failure beyond `tests/test_projector.py::test_project_uses_symlink_when_forced` and no new unplanned skip.
- [ ] Run `cd web && npm run type-check`; expected pass.
- [ ] Run `cd web && npm test`; expected no regression beyond the recorded `appFooter.spec.js` failure.
- [ ] Run `cd web && npm run build`; expected pass with only the recorded warnings.
- [ ] Search staged changes for secrets and public-network installers: `rg -n 'curl.*\|.*sh|0\.0\.0\.0|latest|OPENCODE_SERVER_PASSWORD' src tests infra docs/deployment/offline-opencode.md`; inspect every hit and permit only test assertions, rejection text, localhost-safe documentation, and in-memory environment assignment.
- [ ] Confirm no Claude Code Provider, Agent loop, native tool replacement, MCP runtime, server-side executor, DM8 schema, or frontend feature was added.
- [ ] Record `[test-env]` G1 evidence on an approved target Linux host: exact OS/arch/libc/CPU, disconnected v1.15.11 install, internal model/MCP doctor, example repository edit/test/diff summary, localhost-only socket, cancellation/SIGTERM, and no residual process.

G1 is not complete until the last `[test-env]` checkbox passes. A failed target glibc/CPU check requires selecting a supported enterprise Linux or approved musl artifact and updating the compatibility manifest through a reviewed commit; it must not be bypassed.
