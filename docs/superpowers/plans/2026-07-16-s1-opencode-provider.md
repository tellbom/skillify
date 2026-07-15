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
    model_endpoint: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    allowed_model_hosts: tuple[str, ...] = ()
    credential_env_names: tuple[str, ...] = ()
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
    data: dict[str, Any] = {}
    if paths.config_path.is_file():
        loaded = yaml.safe_load(paths.config_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict): raise ValueError("agent config must be a mapping")
        data = dict(loaded)
    scalar_overrides = {
        "SKILLIFY_AGENT_MODEL_ENDPOINT": "model_endpoint",
        "SKILLIFY_AGENT_MODEL_PROVIDER": "model_provider",
        "SKILLIFY_AGENT_MODEL_NAME": "model_name",
    }
    for env_name, key in scalar_overrides.items():
        if env_name in os.environ: data[key] = os.environ[env_name]
    for env_name, key in {
        "SKILLIFY_AGENT_ALLOWED_MODEL_HOSTS": "allowed_model_hosts",
        "SKILLIFY_AGENT_CREDENTIAL_ENV_NAMES": "credential_env_names",
    }.items():
        if env_name in os.environ:
            data[key] = [value.strip() for value in os.environ[env_name].split(",") if value.strip()]
    config = AgentLocalConfig(
        provider=str(data.get("provider", "opencode")),
        allowed_workspaces=tuple(data.get("allowed_workspaces", ())),
        model_endpoint=data.get("model_endpoint"),
        model_provider=data.get("model_provider"),
        model_name=data.get("model_name"),
        allowed_model_hosts=tuple(data.get("allowed_model_hosts", ())),
        credential_env_names=tuple(data.get("credential_env_names", ())),
        opencode_manifest_path=data.get("opencode_manifest_path"),
        opencode_artifact_root=data.get("opencode_artifact_root"),
    )
    if config.provider != "opencode": raise ValueError("provider must be opencode")
    if any(not Path(value).is_absolute() for value in config.allowed_workspaces):
        raise ValueError("allowed workspaces must be absolute")
    if len(set(config.allowed_workspaces)) != len(config.allowed_workspaces):
        raise ValueError("allowed workspaces must be unique")
    sequence_fields = (config.allowed_model_hosts, config.credential_env_names)
    if any(not isinstance(item, str) for sequence in sequence_fields for item in sequence):
        raise ValueError("model host and credential names must be strings")
    return config

def save_agent_local_config(paths: AgentPaths, config: AgentLocalConfig) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = paths.config_path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(asdict(config), sort_keys=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(paths.config_path)
```

Persisted YAML is the source of truth for endpoint/provider/model, exact allowed
endpoint hosts, and credential **variable names**. `agent init` writes those
safe values. Secret values are never accepted as CLI options or YAML keys; at
Provider start they are read only with `os.environ[name]` for names in
`credential_env_names`. Environment overrides have this exact precedence over
YAML for safe metadata only: `SKILLIFY_AGENT_MODEL_ENDPOINT`,
`SKILLIFY_AGENT_MODEL_PROVIDER`, `SKILLIFY_AGENT_MODEL_NAME`,
`SKILLIFY_AGENT_ALLOWED_MODEL_HOSTS` (comma-separated), and
`SKILLIFY_AGENT_CREDENTIAL_ENV_NAMES` (comma-separated). `load_agent_local_config`
applies those overrides, then constructs `ModelRuntimeConfig`, whose validation
is the final admission gate.

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

- [ ] **Step 1: Create the complete failing CLI test file**

Create `tests/test_cli_agent.py` with this complete content:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import skillify.cli.agent_cmd as agent_cmd
from skillify.cli.agent_cmd import AgentCommandFailure, AgentErrorCode, agent_app
from skillify.common.config import load_agent_paths

runner = CliRunner()

EXPECTED_HELP = """Usage: agent [OPTIONS] COMMAND [ARGS]...

  Manage the local Skillify endpoint agent.

Options:
  --install-completion  Install completion for the current shell.
  --show-completion     Show completion for the current shell, to copy it or
                        customize the installation.
  --help                Show this message and exit.

Commands:
  doctor  Check local endpoint-agent prerequisites.
  init    Register an explicit workspace.
  run     Run an endpoint-agent task locally.
  status  Show local endpoint-agent state.
  stop    Stop the owned local provider process.
  logs    Read redacted local lifecycle logs.
"""


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        "SKILLIFY_AGENT_CONFIG_DIR": str(tmp_path / "config"),
        "SKILLIFY_AGENT_STATE_DIR": str(tmp_path / "state"),
        "SKILLIFY_AGENT_CACHE_DIR": str(tmp_path / "cache"),
        "SKILLIFY_AGENT_LOG_DIR": str(tmp_path / "log"),
    }


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def test_agent_help_exact_snapshot() -> None:
    result = runner.invoke(agent_app, ["--help"], color=False, env={"COLUMNS": "120"})
    assert result.exit_code == 0
    assert result.stdout == EXPECTED_HELP


def test_agent_paths_use_separate_xdg_roots(tmp_path: Path) -> None:
    paths = load_agent_paths(
        {
            "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
            "XDG_STATE_HOME": str(tmp_path / "xdg-state"),
            "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        },
        home=tmp_path / "home",
    )
    assert paths.config_dir == tmp_path / "xdg-config/skillify/agent"
    assert paths.state_dir == tmp_path / "xdg-state/skillify/agent"
    assert paths.cache_dir == tmp_path / "xdg-cache/skillify/agent"
    assert paths.log_dir == tmp_path / "xdg-state/skillify/agent/log"
    assert len({paths.config_dir, paths.state_dir, paths.cache_dir, paths.log_dir}) == 4


def test_agent_init_records_only_resolved_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    result = runner.invoke(
        agent_app,
        ["init", "--workspace", str(workspace), "--format", "json"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 0
    assert _json(result)["code"] == "OK"
    text = (tmp_path / "config/config.yaml").read_text(encoding="utf-8")
    assert str(workspace.resolve()) in text
    assert str(tmp_path.parent) not in text


def test_agent_run_rejects_unregistered_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    result = runner.invoke(
        agent_app,
        ["run", "--workspace", str(workspace), "--prompt-file", "-", "--format", "json"],
        input="inspect\n",
        env=_env(tmp_path),
    )
    assert result.exit_code == 11
    assert _json(result) == {
        "ok": False,
        "code": "AGENT_WORKSPACE_UNAUTHORIZED",
        "message": "workspace is not registered",
        "data": {},
    }


def test_agent_doctor_and_run_need_no_skillify_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_cmd.shutil, "which", lambda name: None)
    doctor = runner.invoke(agent_app, ["doctor", "--format", "json"], env=_env(tmp_path))
    assert doctor.exit_code == 12
    assert _json(doctor)["code"] == "AGENT_PROVIDER_UNAVAILABLE"


@pytest.mark.parametrize(
    ("case", "expected_exit", "expected_code"),
    [
        ("config", 10, "AGENT_CONFIG_INVALID"),
        ("workspace", 11, "AGENT_WORKSPACE_UNAUTHORIZED"),
        ("unavailable", 12, "AGENT_PROVIDER_UNAVAILABLE"),
        ("provider", 13, "AGENT_PROVIDER_FAILED"),
        ("task", 14, "AGENT_TASK_FAILED"),
    ],
)
def test_error_codes_10_through_14_have_stable_json_envelopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_exit: int,
    expected_code: str,
) -> None:
    env = _env(tmp_path)
    workspace = tmp_path / "repo"
    workspace.mkdir()
    if case == "config":
        (tmp_path / "config").mkdir()
        (tmp_path / "config/config.yaml").write_text("[invalid", encoding="utf-8")
        args = ["status", "--format", "json"]
    elif case == "workspace":
        args = ["run", "--workspace", str(workspace), "--prompt-file", "-", "--format", "json"]
    else:
        assert runner.invoke(
            agent_app,
            ["init", "--workspace", str(workspace), "--format", "json"],
            env=env,
        ).exit_code == 0
        monkeypatch.setattr(agent_cmd.shutil, "which", lambda name: None if case == "unavailable" else "/bin/opencode")
        if case == "provider":
            monkeypatch.setattr(
                agent_cmd,
                "_run_local_task",
                lambda workspace, prompt: (_ for _ in ()).throw(
                    AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider start failed")
                ),
            )
        if case == "task":
            monkeypatch.setattr(agent_cmd, "_run_local_task", lambda workspace, prompt: "failed")
        args = ["run", "--workspace", str(workspace), "--prompt-file", "-", "--format", "json"]
    result = runner.invoke(agent_app, args, input="inspect\n", env=env)
    assert result.exit_code == expected_exit
    payload = _json(result)
    assert payload["ok"] is False
    assert payload["code"] == expected_code
    assert set(payload) == {"ok", "code", "message", "data"}


def test_status_stop_and_logs_are_local_and_idempotent(tmp_path: Path) -> None:
    env = _env(tmp_path)
    status = runner.invoke(agent_app, ["status", "--format", "json"], env=env)
    stop = runner.invoke(agent_app, ["stop", "--format", "json"], env=env)
    logs = runner.invoke(agent_app, ["logs", "--lines", "5", "--format", "json"], env=env)
    assert _json(status)["data"] == {"state": "stopped"}
    assert _json(stop)["code"] == "OK"
    assert _json(logs)["data"] == {"lines": []}
    assert {status.exit_code, stop.exit_code, logs.exit_code} == {0}
```

- [ ] **Step 2: Run Task 1.1 RED tests**

Run:

```bash
uv run --no-sync pytest tests/test_cli_agent.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'skillify.cli.agent_cmd'` or assertions fail because `agent` is not registered. No network request is permitted.

- [ ] **Step 3: Add the complete configuration patch to `common/config.py`**

Add `Mapping` to the typing import, add `AgentPaths` and `AgentLocalConfig` plus
the three complete functions in the interface block above after
`skillify_home()`, and use this exact YAML shape:

```yaml
provider: opencode
allowed_workspaces:
  - /resolved/absolute/workspace
model_endpoint: https://model.intranet.example/v1
model_provider: internal-openai
model_name: code-model-1
allowed_model_hosts:
  - model.intranet.example
credential_env_names:
  - INTERNAL_MODEL_API_KEY
opencode_manifest_path: null
opencode_artifact_root: null
```

- [ ] **Step 4: Create the complete six-command module**

Create `src/skillify/cli/agent_cmd.py` with this complete Task 1.1 implementation:

```python
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

import typer

from skillify.common.config import (
    AgentLocalConfig,
    load_agent_local_config,
    load_agent_paths,
    save_agent_local_config,
)

agent_app = typer.Typer(
    name="agent",
    help="Manage the local Skillify endpoint agent.",
    no_args_is_help=True,
    rich_markup_mode=None,
)


class AgentErrorCode(str, Enum):
    OK = "OK"
    CONFIG_INVALID = "AGENT_CONFIG_INVALID"
    WORKSPACE_UNAUTHORIZED = "AGENT_WORKSPACE_UNAUTHORIZED"
    PROVIDER_UNAVAILABLE = "AGENT_PROVIDER_UNAVAILABLE"
    PROVIDER_FAILED = "AGENT_PROVIDER_FAILED"
    TASK_FAILED = "AGENT_TASK_FAILED"


class AgentExit(IntEnum):
    OK = 0
    CONFIG_INVALID = 10
    WORKSPACE_UNAUTHORIZED = 11
    PROVIDER_UNAVAILABLE = 12
    PROVIDER_FAILED = 13
    TASK_FAILED = 14


_EXIT_BY_CODE = {
    AgentErrorCode.OK: AgentExit.OK,
    AgentErrorCode.CONFIG_INVALID: AgentExit.CONFIG_INVALID,
    AgentErrorCode.WORKSPACE_UNAUTHORIZED: AgentExit.WORKSPACE_UNAUTHORIZED,
    AgentErrorCode.PROVIDER_UNAVAILABLE: AgentExit.PROVIDER_UNAVAILABLE,
    AgentErrorCode.PROVIDER_FAILED: AgentExit.PROVIDER_FAILED,
    AgentErrorCode.TASK_FAILED: AgentExit.TASK_FAILED,
}


class AgentCommandFailure(Exception):
    def __init__(self, code: AgentErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _emit(*, ok: bool, code: AgentErrorCode, message: str, data: dict[str, Any], output: str) -> None:
    payload = {"ok": ok, "code": code.value, "message": message, "data": data}
    if output == "json":
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(message)


def _fail(error: AgentCommandFailure, output: str) -> None:
    _emit(ok=False, code=error.code, message=error.message, data={}, output=output)
    raise typer.Exit(int(_EXIT_BY_CODE[error.code]))


def _config():
    paths = load_agent_paths()
    try:
        return paths, load_agent_local_config(paths)
    except (OSError, TypeError, ValueError) as exc:
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "agent config is invalid") from exc


def _workspace(value: Path, config: AgentLocalConfig) -> Path:
    try:
        resolved = value.resolve(strict=True)
    except OSError as exc:
        raise AgentCommandFailure(AgentErrorCode.WORKSPACE_UNAUTHORIZED, "workspace is not registered") from exc
    if str(resolved) not in config.allowed_workspaces:
        raise AgentCommandFailure(AgentErrorCode.WORKSPACE_UNAUTHORIZED, "workspace is not registered")
    return resolved


def _read_prompt(path: str) -> str:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    if not text.strip():
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "prompt file is empty")
    return text


def _run_local_task(workspace: Path, prompt: str) -> str:
    if shutil.which("opencode") is None:
        raise AgentCommandFailure(AgentErrorCode.PROVIDER_UNAVAILABLE, "opencode is not installed")
    raise AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider adapter is not installed")


@agent_app.command()
def init(
    workspace: Path = typer.Option(..., "--workspace"),
    provider: str = typer.Option("opencode", "--provider"),
    model_endpoint: str | None = typer.Option(None, "--model-endpoint"),
    model_provider: str | None = typer.Option(None, "--model-provider"),
    model_name: str | None = typer.Option(None, "--model"),
    allowed_model_host: list[str] = typer.Option([], "--allowed-model-host"),
    credential_env: list[str] = typer.Option([], "--credential-env"),
    output: str = typer.Option("text", "--format"),
) -> None:
    try:
        if provider != "opencode":
            raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "provider must be opencode")
        resolved = workspace.resolve(strict=True)
        if not resolved.is_dir() or resolved in {Path("/"), Path.home().resolve()}:
            raise AgentCommandFailure(AgentErrorCode.WORKSPACE_UNAUTHORIZED, "workspace is not allowed")
        paths, config = _config()
        allowed = tuple(sorted(set(config.allowed_workspaces) | {str(resolved)}))
        updated = replace(
            config, provider="opencode", allowed_workspaces=allowed,
            model_endpoint=model_endpoint or config.model_endpoint,
            model_provider=model_provider or config.model_provider,
            model_name=model_name or config.model_name,
            allowed_model_hosts=tuple(allowed_model_host) or config.allowed_model_hosts,
            credential_env_names=tuple(credential_env) or config.credential_env_names,
        )
        save_agent_local_config(paths, updated)
        _emit(ok=True, code=AgentErrorCode.OK, message="workspace registered", data={"workspace": str(resolved)}, output=output)
    except AgentCommandFailure as exc:
        _fail(exc, output)


@agent_app.command()
def doctor(output: str = typer.Option("text", "--format")) -> None:
    try:
        _config()
        executable = shutil.which("opencode")
        if executable is None:
            raise AgentCommandFailure(AgentErrorCode.PROVIDER_UNAVAILABLE, "opencode is not installed")
        _emit(ok=True, code=AgentErrorCode.OK, message="local prerequisites available", data={"opencode": executable}, output=output)
    except AgentCommandFailure as exc:
        _fail(exc, output)


@agent_app.command()
def run(
    workspace: Path = typer.Option(..., "--workspace"),
    prompt_file: str = typer.Option(..., "--prompt-file"),
    output: str = typer.Option("text", "--format"),
) -> None:
    try:
        _, config = _config()
        resolved = _workspace(workspace, config)
        result = _run_local_task(resolved, _read_prompt(prompt_file))
        if result != "succeeded":
            raise AgentCommandFailure(AgentErrorCode.TASK_FAILED, "task failed")
        _emit(ok=True, code=AgentErrorCode.OK, message="task succeeded", data={"state": result}, output=output)
    except AgentCommandFailure as exc:
        _fail(exc, output)


@agent_app.command()
def status(output: str = typer.Option("text", "--format")) -> None:
    try:
        paths, _ = _config()
        data = json.loads(paths.runtime_path.read_text(encoding="utf-8")) if paths.runtime_path.is_file() else {"state": "stopped"}
        _emit(ok=True, code=AgentErrorCode.OK, message=str(data["state"]), data=data, output=output)
    except (json.JSONDecodeError, KeyError, OSError):
        _fail(AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "runtime state is invalid"), output)


@agent_app.command()
def stop(output: str = typer.Option("text", "--format")) -> None:
    paths = load_agent_paths()
    paths.runtime_path.unlink(missing_ok=True)
    _emit(ok=True, code=AgentErrorCode.OK, message="stopped", data={"state": "stopped"}, output=output)


@agent_app.command()
def logs(
    lines: int = typer.Option(100, "--lines", min=1, max=10000),
    output: str = typer.Option("text", "--format"),
) -> None:
    path = load_agent_paths().log_path
    content = path.read_text(encoding="utf-8").splitlines()[-lines:] if path.is_file() else []
    _emit(ok=True, code=AgentErrorCode.OK, message="logs", data={"lines": content}, output=output)
```

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

Expected: compileall exits 0 and `11 passed`, with zero failed/skipped.

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

`events.py` public interface defines both protocol constants explicitly:

```python
TASK_PROTOCOL_VERSION = 1
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
    task_protocol_version: int
    provider_contract_version: int
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
            "task_protocol_version": self.task_protocol_version,
            "provider_contract_version": self.provider_contract_version,
            "timestamp": self.timestamp.isoformat(),
            "type": self.type.value,
            "state": self.state.value,
            "details": dict(self.details),
        }
```

Allowed detail keys are exactly `sequence`, `tool_name`, `tool_call_id`, `exit_code`, `test_count`, `artifact_count`, `reason_code`, and `result_state`. `__post_init__` copies the caller mapping and replaces it with `MappingProxyType(copied)` after validating scalar values and keys; it also requires a UTC-aware timestamp and both version fields equal to 1. This prevents caller mutation and prompt/source/secret/environment/database/raw input/output fields by construction.

`provider.py` public interface:

```python
@dataclass(frozen=True)
class ProviderCapability:
    provider: str
    provider_version: str
    provider_contract_version: int
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
    runtime: ModelRuntimeConfig
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
    task_protocol_version: int = TASK_PROTOCOL_VERSION
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

- [ ] **Step 1: Create the complete failing Provider contract test file**

Create `tests/test_provider_contract.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from skillify.agent.events import (
    PROVIDER_CONTRACT_VERSION,
    TASK_PROTOCOL_VERSION,
    EventType,
    TaskEvent,
    TaskState,
)
from skillify.agent.fake_provider import FakeOutcome, FakeProvider
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec, TaskSpec

NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


def _runtime() -> ModelRuntimeConfig:
    return ModelRuntimeConfig(
        provider="internal-openai",
        endpoint="https://model.intranet.example/v1",
        model="code-model-1",
        allowed_endpoint_hosts=("model.intranet.example",),
        credential_env_names=("INTERNAL_MODEL_API_KEY",),
    )


def _start(tmp_path: Path) -> ProviderStartSpec:
    workspace = (tmp_path / "repo").resolve()
    workspace.mkdir()
    return ProviderStartSpec(
        workspace=workspace,
        allowed_paths=(workspace,),
        config_dir=tmp_path / "config",
        runtime=_runtime(),
    )


def _provider(outcome: FakeOutcome = FakeOutcome.SUCCEED) -> FakeProvider:
    values = iter(("handle-1", "session-1"))
    return FakeProvider(outcome=outcome, clock=lambda: NOW, id_factory=lambda: next(values))


def test_protocol_versions_are_explicit_and_stable() -> None:
    assert TASK_PROTOCOL_VERSION == 1
    assert PROVIDER_CONTRACT_VERSION == 1
    assert TaskSpec(task_id="task-1", prompt="work").task_protocol_version == 1


@pytest.mark.parametrize("kwargs", [
    {"task_id": "", "prompt": "work"},
    {"task_id": "task", "prompt": ""},
    {"task_id": "task", "prompt": "work", "task_protocol_version": 2},
    {"task_id": "task", "prompt": "work", "timeout_seconds": 0},
])
def test_task_spec_rejects_invalid_ids_protocol_prompt_and_timeout(kwargs) -> None:
    with pytest.raises(ValueError): TaskSpec(**kwargs)


def test_runtime_config_is_immutable_validated_and_redacted() -> None:
    config = _runtime()
    assert config.redacted() == {
        "provider": "internal-openai",
        "endpoint_host": "model.intranet.example",
        "model": "code-model-1",
        "credential_env_names": ["INTERNAL_MODEL_API_KEY"],
    }
    with pytest.raises((AttributeError, TypeError)):
        config.model = "changed"
    with pytest.raises(ValueError, match="allowlisted"):
        ModelRuntimeConfig("p", "https://api.openai.com/v1", "m", ("model.intranet.example",), ("API_KEY",))
    with pytest.raises(ValueError, match="credential"):
        ModelRuntimeConfig("p", "https://model.intranet.example/v1", "m", ("model.intranet.example",), ("KEY=value",))


def test_task_event_defensively_copies_details_and_rejects_sensitive_fields() -> None:
    caller = {"sequence": 1}
    event = TaskEvent(
        task_id="task-1", session_id="session-1", provider="fake",
        provider_version="1.0.0", task_protocol_version=1,
        provider_contract_version=1, timestamp=NOW,
        type=EventType.TASK_ACCEPTED, state=TaskState.QUEUED, details=caller,
    )
    caller["prompt"] = "secret"
    assert dict(event.details) == {"sequence": 1}
    with pytest.raises(TypeError):
        event.details["secret"] = "value"
    with pytest.raises(ValueError, match="event detail"):
        TaskEvent(
            task_id="t", session_id="s", provider="p", provider_version="1",
            task_protocol_version=1, provider_contract_version=1, timestamp=NOW,
            type=EventType.TASK_ACCEPTED, state=TaskState.QUEUED,
            details={"source_code": "print('secret')"},
        )


def test_fake_provider_startup_and_ordered_success(tmp_path: Path) -> None:
    provider = _provider()
    handle = provider.start(_start(tmp_path))
    session = provider.create_session(handle, TaskSpec("task-1", "private prompt"))
    events = list(provider.stream_events(handle, session))
    assert [event.type.value for event in events] == [
        "task.accepted", "plan.ready", "tool.requested", "tool.completed",
        "test.completed", "artifact.created", "task.finished",
    ]
    assert events[-1].state is TaskState.SUCCEEDED
    assert all(event.task_protocol_version == event.provider_contract_version == 1 for event in events)
    assert "private prompt" not in repr(events)


def test_fake_provider_cancellation_finishes_cancelled(tmp_path: Path) -> None:
    provider = _provider()
    handle = provider.start(_start(tmp_path))
    session = provider.create_session(handle, TaskSpec("task-1", "private"))
    assert provider.cancel(handle, session).state is TaskState.CANCELLED
    events = list(provider.stream_events(handle, session))
    assert [(event.type, event.state) for event in events] == [(EventType.TASK_FINISHED, TaskState.CANCELLED)]


@pytest.mark.parametrize(
    ("outcome", "terminal"),
    [(FakeOutcome.FAIL, TaskState.FAILED), (FakeOutcome.BLOCK, TaskState.BLOCKED)],
)
def test_fake_provider_abnormal_outcomes(tmp_path: Path, outcome: FakeOutcome, terminal: TaskState) -> None:
    provider = _provider(outcome)
    handle = provider.start(_start(tmp_path))
    session = provider.create_session(handle, TaskSpec("task-1", "private"))
    events = list(provider.stream_events(handle, session))
    assert events[-1].state is terminal
    assert events[-1].type in {EventType.TASK_BLOCKED, EventType.TASK_FINISHED}


def test_fake_provider_stop_cleans_handles_and_sessions(tmp_path: Path) -> None:
    provider = _provider()
    handle = provider.start(_start(tmp_path))
    provider.create_session(handle, TaskSpec("task-1", "private"))
    assert provider.stop(handle).state is TaskState.SUCCEEDED
    assert provider.live_handle_count == provider.live_session_count == 0
    assert provider.stop(handle).state is TaskState.SUCCEEDED
```

- [ ] **Step 2: Run Task 1.2 RED tests**

Run:

```bash
uv run --no-sync pytest tests/test_provider_contract.py -q
```

Expected: import/collection failure because `skillify.agent` does not exist.

- [ ] **Step 3: Create the complete immutable event module**

Create `src/skillify/agent/events.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

TASK_PROTOCOL_VERSION = 1
PROVIDER_CONTRACT_VERSION = 1
JsonScalar = str | int | float | bool | None
_DETAIL_KEYS = frozenset({
    "sequence", "tool_name", "tool_call_id", "exit_code", "test_count",
    "artifact_count", "reason_code", "result_state",
})


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


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    session_id: str
    provider: str
    provider_version: str
    task_protocol_version: int
    provider_contract_version: int
    timestamp: datetime
    type: EventType
    state: TaskState
    details: Mapping[str, JsonScalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.task_protocol_version != TASK_PROTOCOL_VERSION:
            raise ValueError("unsupported task protocol version")
        if self.provider_contract_version != PROVIDER_CONTRACT_VERSION:
            raise ValueError("unsupported provider contract version")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() != timezone.utc.utcoffset(self.timestamp):
            raise ValueError("timestamp must be UTC-aware")
        copied = dict(self.details)
        invalid = set(copied) - _DETAIL_KEYS
        if invalid or any(not isinstance(v, (str, int, float, bool, type(None))) for v in copied.values()):
            raise ValueError("invalid event detail")
        object.__setattr__(self, "details", MappingProxyType(copied))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id, "session_id": self.session_id,
            "provider": self.provider, "provider_version": self.provider_version,
            "task_protocol_version": self.task_protocol_version,
            "provider_contract_version": self.provider_contract_version,
            "timestamp": self.timestamp.isoformat(), "type": self.type.value,
            "state": self.state.value, "details": dict(self.details),
        }
```

- [ ] **Step 4: Create the complete Provider types and runtime configuration**

Create `src/skillify/agent/provider.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol
from urllib.parse import urlsplit

from skillify.agent.events import PROVIDER_CONTRACT_VERSION, TASK_PROTOCOL_VERSION, TaskEvent, TaskState

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class ModelRuntimeConfig:
    provider: str
    endpoint: str
    model: str
    allowed_endpoint_hosts: tuple[str, ...]
    credential_env_names: tuple[str, ...]

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("model endpoint must be an absolute HTTP(S) URL without userinfo")
        if parsed.query or parsed.fragment or parsed.hostname not in self.allowed_endpoint_hosts:
            raise ValueError("model endpoint host must be allowlisted")
        if not self.provider or not self.model:
            raise ValueError("provider and model are required")
        if not self.credential_env_names or any(not _ENV_NAME.fullmatch(name) for name in self.credential_env_names):
            raise ValueError("credential environment-variable names are invalid")

    def redacted(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "endpoint_host": urlsplit(self.endpoint).hostname,
            "model": self.model,
            "credential_env_names": list(self.credential_env_names),
        }


@dataclass(frozen=True)
class ProviderCapability:
    provider: str
    provider_version: str
    provider_contract_version: int = PROVIDER_CONTRACT_VERSION
    supports_cancel: bool = True
    supports_streaming: bool = True


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
    runtime: ModelRuntimeConfig
    startup_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.workspace.is_absolute() or self.workspace not in self.allowed_paths:
            raise ValueError("workspace must be an explicit allowed absolute path")
        if any(not path.is_absolute() for path in self.allowed_paths):
            raise ValueError("allowed paths must be absolute")
        if min(self.startup_timeout_seconds, self.shutdown_timeout_seconds) <= 0:
            raise ValueError("timeouts must be positive")


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
    task_protocol_version: int = TASK_PROTOCOL_VERSION
    timeout_seconds: float = 900.0

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.prompt.strip():
            raise ValueError("task id and prompt must be non-empty")
        if self.task_protocol_version != TASK_PROTOCOL_VERSION:
            raise ValueError("unsupported task protocol version")
        if self.timeout_seconds <= 0:
            raise ValueError("task timeout must be positive")


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
    def probe(self) -> ProviderProbe: """Return local availability and capability."""
    def start(self, spec: ProviderStartSpec) -> ProviderHandle: """Start one isolated provider."""
    def create_session(self, handle: ProviderHandle, spec: TaskSpec) -> ProviderSession: """Create one task session."""
    def stream_events(self, handle: ProviderHandle, session: ProviderSession) -> Iterator[TaskEvent]: """Yield safe ordered events."""
    def cancel(self, handle: ProviderHandle, session: ProviderSession) -> ProviderResult: """Cancel one session."""
    def stop(self, handle: ProviderHandle) -> ProviderResult: """Stop and clean one provider."""
```

- [ ] **Step 5: Create the complete deterministic FakeProvider**

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Callable, Iterator

from skillify.agent.events import EventType, TaskEvent, TaskState
from skillify.agent.provider import (
    ProviderCapability, ProviderHandle, ProviderProbe, ProviderResult,
    ProviderSession, ProviderStartSpec, TaskSpec,
)


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

    @property
    def live_handle_count(self) -> int: return len(self.handles)
    @property
    def live_session_count(self) -> int: return len(self.sessions)

    def probe(self) -> ProviderProbe:
        return ProviderProbe(True, ProviderCapability("fake", "1.0.0"))

    def start(self, spec: ProviderStartSpec) -> ProviderHandle:
        handle = ProviderHandle(self.id_factory(), "fake", "1.0.0", "fake://local", 1)
        self.handles[handle.handle_id] = handle
        return handle

    def create_session(self, handle: ProviderHandle, spec: TaskSpec) -> ProviderSession:
        if handle.handle_id not in self.handles: raise ValueError("unknown handle")
        session = ProviderSession(spec.task_id, self.id_factory(), handle.handle_id)
        self.sessions[session.session_id] = session
        return session

    def _event(self, session: ProviderSession, kind: EventType, state: TaskState, sequence: int) -> TaskEvent:
        return TaskEvent(session.task_id, session.session_id, "fake", "1.0.0", 1, 1,
                         self.clock(), kind, state, {"sequence": sequence})

    def stream_events(self, handle: ProviderHandle, session: ProviderSession) -> Iterator[TaskEvent]:
        if session.session_id in self.cancelled_session_ids:
            yield self._event(session, EventType.TASK_FINISHED, TaskState.CANCELLED, 1)
            return
        if self.outcome is FakeOutcome.FAIL:
            yield self._event(session, EventType.TASK_ACCEPTED, TaskState.QUEUED, 1)
            yield self._event(session, EventType.TASK_FINISHED, TaskState.FAILED, 2)
            return
        if self.outcome is FakeOutcome.BLOCK:
            yield self._event(session, EventType.TASK_ACCEPTED, TaskState.QUEUED, 1)
            yield self._event(session, EventType.TASK_BLOCKED, TaskState.BLOCKED, 2)
            return
        sequence = [
            (EventType.TASK_ACCEPTED, TaskState.QUEUED),
            (EventType.PLAN_READY, TaskState.RUNNING),
            (EventType.TOOL_REQUESTED, TaskState.AWAITING_APPROVAL),
            (EventType.TOOL_COMPLETED, TaskState.RUNNING),
            (EventType.TEST_COMPLETED, TaskState.RUNNING),
            (EventType.ARTIFACT_CREATED, TaskState.RUNNING),
            (EventType.TASK_FINISHED, TaskState.SUCCEEDED),
        ]
        for index, (kind, state) in enumerate(sequence, 1):
            yield self._event(session, kind, state, index)

    def cancel(self, handle: ProviderHandle, session: ProviderSession) -> ProviderResult:
        self.cancelled_session_ids.add(session.session_id)
        return ProviderResult(TaskState.CANCELLED)

    def stop(self, handle: ProviderHandle) -> ProviderResult:
        self.handles.pop(handle.handle_id, None)
        stale = [key for key, value in self.sessions.items() if value.handle_id == handle.handle_id]
        for key in stale: self.sessions.pop(key, None)
        return ProviderResult(TaskState.SUCCEEDED)
```

- [ ] **Step 6: Create the complete public contract export**

Create `src/skillify/agent/__init__.py`:

```python
from skillify.agent.events import (
    PROVIDER_CONTRACT_VERSION, TASK_PROTOCOL_VERSION, EventType, TaskEvent, TaskState,
)
from skillify.agent.fake_provider import FakeOutcome, FakeProvider
from skillify.agent.provider import (
    AgentProvider, ModelRuntimeConfig, ProviderCapability, ProviderHandle,
    ProviderProbe, ProviderResult, ProviderSession, ProviderStartSpec, TaskSpec,
)

__all__ = [
    "AgentProvider", "EventType", "FakeOutcome", "FakeProvider",
    "ModelRuntimeConfig", "PROVIDER_CONTRACT_VERSION", "ProviderCapability",
    "ProviderHandle", "ProviderProbe", "ProviderResult", "ProviderSession",
    "ProviderStartSpec", "TASK_PROTOCOL_VERSION", "TaskEvent", "TaskSpec", "TaskState",
]
```

- [ ] **Step 7: Run Task 1.2 GREEN tests**

Run:

```bash
uv run --no-sync python -m compileall -q src
uv run --no-sync pytest tests/test_provider_contract.py -q
```

Expected: compileall exits 0 and `12 passed`, with zero failed/skipped.

- [ ] **Step 8: Commit Task 1.2**

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
- Produces: `OpenCodeProvider`, `OpenCodeError`, `HttpTransport`,
  `RequestsTransport`, and `ManagedProcess`, with their complete definitions in
  Step 3 below.

- [ ] **Step 1: Create the complete fake HTTP/process contract test file**

Create `tests/test_opencode_provider_contract.py`:

```python
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
from skillify.agent.providers.opencode import OpenCodeProvider, ProviderCrashed, ProviderTimeout

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
    events = list(provider.stream_events(handle, session))
    assert [e.type for e in events] == [EventType.TASK_ACCEPTED, EventType.PLAN_READY, EventType.TOOL_REQUESTED, EventType.TEST_COMPLETED, EventType.ARTIFACT_CREATED, EventType.TASK_FINISHED]
    assert events[-1].state is TaskState.SUCCEEDED
    assert "private" not in repr(events) and "source" not in repr(events) and "secret.py" not in repr(events)


def test_cancel_timeout_crash_and_stop_cleanup(tmp_path, fake_server, monkeypatch):
    provider, _, killed, process = _provider(fake_server, monkeypatch)
    handle = provider.start(_spec(tmp_path)); session = provider.create_session(handle, TaskSpec("task-1", "private"))
    assert provider.cancel(handle, session).state is TaskState.CANCELLED
    assert Handler.requests[-1][1] == "/session/session-1/abort"
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
```

- [ ] **Step 2: Run Task 1.3 RED contract tests**

Run:

```bash
uv run --no-sync pytest tests/test_opencode_provider_contract.py -q
```

Expected: import failure for `skillify.agent.providers.opencode`.

- [ ] **Step 3: Create the complete OpenCode HTTP/SSE and process implementation**

Create `src/skillify/agent/providers/opencode.py` with this complete content:

```python
from __future__ import annotations

import base64, json, os, secrets, shutil, signal, socket, subprocess, time, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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
    def request_json(self, method, url, *, password, timeout, body=None):
        response = requests.request(method, url, headers={"Authorization": _auth(password)}, json=body, timeout=timeout)
        response.raise_for_status()
        return {} if response.status_code == 204 else response.json()
    def iter_sse(self, url, *, password, timeout):
        with requests.get(url, headers={"Authorization": _auth(password)}, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if line and line.startswith("data: "):
                    value = json.loads(line[6:])
                    if isinstance(value, dict): yield value


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def linux_process_start_token(pid: int) -> str:
    return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]


@dataclass
class _Live:
    process: ManagedProcess
    password: str
    spec: ProviderStartSpec
    pgid: int
    start_token: str


class OpenCodeProvider:
    def __init__(self, *, executable="opencode", transport=None, popen=subprocess.Popen,
                 port_factory: Callable[[], int] = find_free_port,
                 password_factory=lambda: secrets.token_urlsafe(32),
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 monotonic=time.monotonic, sleep=time.sleep,
                 killpg=os.killpg, getpgid=os.getpgid, process_start_token=linux_process_start_token):
        self.executable, self.transport, self.popen = executable, transport or RequestsTransport(), popen
        self.port_factory, self.password_factory, self.clock = port_factory, password_factory, clock
        self.monotonic, self.sleep, self.killpg, self.getpgid = monotonic, sleep, killpg, getpgid
        self.process_start_token, self._live = process_start_token, {}
        self._tasks = {}

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
        pgid = process.pid
        try:
            pgid = self.getpgid(process.pid)
            start_token = self.process_start_token(process.pid)
            while True:
                if process.poll() is not None: raise ProviderCrashed("opencode exited during startup")
                if self.monotonic() >= deadline: raise ProviderTimeout("opencode startup timed out")
                health = self.transport.request_json("GET", base_url + "/global/health", password=password, timeout=0.5)
                if health.get("healthy") is True: break
                self.sleep(0.05)
        except requests.RequestException:
            while self.monotonic() < deadline and process.poll() is None:
                self.sleep(0.05)
                try:
                    health = self.transport.request_json("GET", base_url + "/global/health", password=password, timeout=0.5)
                    if health.get("healthy") is True: break
                except requests.RequestException:
                    continue
            else:
                try: self._terminate(process, pgid, spec.shutdown_timeout_seconds)
                finally: password = ""
                raise ProviderTimeout("opencode startup timed out")
        except Exception:
            try: self._terminate(process, pgid, spec.shutdown_timeout_seconds)
            finally: password = ""
            raise
        handle = ProviderHandle(uuid.uuid4().hex, "opencode", str(health["version"]), base_url, process.pid)
        self._live[handle.handle_id] = _Live(process, password, spec, pgid, start_token)
        return handle

    def _terminate(self, process: ManagedProcess, pgid: int, timeout: float) -> None:
        if process.poll() is not None: return
        self.killpg(pgid, signal.SIGTERM)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.killpg(pgid, signal.SIGKILL)
            process.wait(timeout=1)

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
        self._tasks[session.session_id] = spec
        self.transport.request_json("POST", handle.base_url + f"/session/{session.session_id}/prompt_async",
                                    password=live.password, timeout=5, body={"parts": [{"type": "text", "text": spec.prompt}]})
        return session

    def _event(self, handle, session, kind, state, sequence, details=None):
        values = {"sequence": sequence}; values.update(details or {})
        return TaskEvent(session.task_id, session.session_id, "opencode", handle.provider_version, 1, 1,
                         self.clock(), kind, state, values)

    def stream_events(self, handle, session):
        live = self._live[handle.handle_id]
        if live.process.poll() is not None: raise ProviderCrashed("opencode exited")
        task = self._tasks[session.session_id]; deadline = self.monotonic() + task.timeout_seconds
        sequence = 1; yield self._event(handle, session, EventType.TASK_ACCEPTED, TaskState.QUEUED, sequence)
        try:
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
                    error = props.get("error", {}); reason = error.get("name", "OPENCODE_ERROR") if isinstance(error, dict) else "OPENCODE_ERROR"
                    yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.FAILED, sequence, {"reason_code": str(reason)})
                    return
                elif kind == "session.idle":
                    yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.SUCCEEDED, sequence, {"result_state": "succeeded"})
                    return
        except requests.RequestException:
            self._abort_quietly(handle, session, live)
            sequence += 1
            yield self._event(handle, session, EventType.TASK_BLOCKED, TaskState.BLOCKED, sequence, {"reason_code": "PROVIDER_NETWORK"})
            sequence += 1
            yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.FAILED, sequence, {"reason_code": "PROVIDER_NETWORK"})
            return
        self._abort_quietly(handle, session, live)
        sequence += 1
        yield self._event(handle, session, EventType.TASK_BLOCKED, TaskState.BLOCKED, sequence, {"reason_code": "PROVIDER_TIMEOUT"})
        sequence += 1
        yield self._event(handle, session, EventType.TASK_FINISHED, TaskState.FAILED, sequence, {"reason_code": "PROVIDER_TIMEOUT"})

    def cancel(self, handle, session):
        live = self._live[handle.handle_id]
        self.transport.request_json("POST", handle.base_url + f"/session/{session.session_id}/abort",
                                    password=live.password, timeout=5)
        return ProviderResult(TaskState.CANCELLED)

    def stop(self, handle):
        live = self._live.pop(handle.handle_id, None)
        if live is None: return ProviderResult(TaskState.SUCCEEDED)
        try:
            try: self.transport.request_json("POST", handle.base_url + "/instance/dispose", password=live.password, timeout=1)
            except Exception: pass
            self._terminate(live.process, live.pgid, live.spec.shutdown_timeout_seconds)
        finally:
            live.password = ""
        return ProviderResult(TaskState.SUCCEEDED)

    def ownership(self, handle):
        live = self._live[handle.handle_id]
        return {"pid": handle.process_id, "pgid": live.pgid, "start_token": live.start_token,
                "executable": self.executable}
```

- [ ] **Step 4: Create the complete OpenCode Provider export**

Create `src/skillify/agent/providers/__init__.py`:

```python
from skillify.agent.providers.opencode import (
    OpenCodeError, OpenCodeProvider, ProviderCrashed, ProviderTimeout,
)

__all__ = ["OpenCodeError", "OpenCodeProvider", "ProviderCrashed", "ProviderTimeout"]
```

- [ ] **Step 5: Add atomic cross-CLI ownership state and redacted lifecycle logs**

Add the state/helper definitions to `agent_cmd.py` and replace the Task 1.1
`status`/`stop` functions with the versions in this block. S1 intentionally supports
foreground `run` only; there is no `--background` option. The foreground owner
writes runtime state immediately after start so a second CLI can run
`status`/`stop`, and removes it in `finally`. Only the allowlisted lifecycle
fields below are persisted:

```python
@dataclass(frozen=True)
class AgentRuntimeState:
    schema_version: int
    owner_uid: int
    pid: int
    pgid: int
    process_start_token: str
    executable: str
    workspace_hash: str
    task_id: str
    session_id: str
    provider_version: str
    started_at: str
    state: str


def write_runtime_state(paths: AgentPaths, state: AgentRuntimeState) -> None:
    paths.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = paths.runtime_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(asdict(state), sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, paths.runtime_path)


def read_runtime_state(paths: AgentPaths) -> AgentRuntimeState | None:
    if not paths.runtime_path.is_file(): return None
    return AgentRuntimeState(**json.loads(paths.runtime_path.read_text(encoding="utf-8")))


def validate_owned_process(state: AgentRuntimeState, inspector) -> bool:
    return (state.schema_version == 1 and state.owner_uid == os.getuid() and
            inspector.is_alive(state.pid) and inspector.pgid(state.pid) == state.pgid and
            inspector.start_token(state.pid) == state.process_start_token and
            Path(inspector.executable(state.pid)).name == Path(state.executable).name)


def stop_owned_process(paths: AgentPaths, inspector, killpg=os.killpg) -> bool:
    state = read_runtime_state(paths)
    if state is None: return True
    if not validate_owned_process(state, inspector):
        paths.runtime_path.unlink(missing_ok=True)
        return False
    # Revalidate immediately before signaling to close the PID-reuse window.
    if not validate_owned_process(state, inspector):
        paths.runtime_path.unlink(missing_ok=True)
        return False
    killpg(state.pgid, signal.SIGTERM)
    if not inspector.wait_exited(state.pid, 5.0):
        killpg(state.pgid, signal.SIGKILL)
        if not inspector.wait_exited(state.pid, 1.0):
            return False
    paths.runtime_path.unlink(missing_ok=True)
    return True


def append_agent_log(paths: AgentPaths, event: str, **fields: str) -> None:
    allowed = {key: value for key, value in fields.items() if key in {
        "task_id", "session_id", "provider_version", "state", "reason_code"
    }}
    paths.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with paths.log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": event, **allowed}, sort_keys=True) + "\n")
    paths.log_path.chmod(0o600)


class LinuxProcessInspector:
    def is_alive(self, pid: int) -> bool:
        return Path(f"/proc/{pid}").is_dir()
    def pgid(self, pid: int) -> int:
        return os.getpgid(pid)
    def start_token(self, pid: int) -> str:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]
    def executable(self, pid: int) -> str:
        return os.readlink(f"/proc/{pid}/exe")
    def wait_exited(self, pid: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while self.is_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        return not self.is_alive(pid)


@agent_app.command()
def status(output: str = typer.Option("text", "--format")) -> None:
    paths = load_agent_paths(); state = read_runtime_state(paths)
    if state is None:
        data = {"state": "stopped"}
    elif validate_owned_process(state, LinuxProcessInspector()):
        data = {"state": state.state, "task_id": state.task_id, "session_id": state.session_id}
    else:
        paths.runtime_path.unlink(missing_ok=True); data = {"state": "stopped"}
    _emit(ok=True, code=AgentErrorCode.OK, message=str(data["state"]), data=data, output=output)


@agent_app.command()
def stop(output: str = typer.Option("text", "--format")) -> None:
    paths = load_agent_paths()
    if not stop_owned_process(paths, LinuxProcessInspector()):
        _fail(AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "runtime owner identity mismatch"), output)
    _emit(ok=True, code=AgentErrorCode.OK, message="stopped", data={"state": "stopped"}, output=output)
```

- [ ] **Step 6: Add complete cross-CLI lifecycle tests**

Append to `tests/test_opencode_provider_contract.py`:

```python
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
```

- [ ] **Step 7: Add complete RED tests for CLI-to-Provider execution wiring**

Append to `tests/test_opencode_provider_contract.py`:

```python
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
```

- [ ] **Step 8: Replace the Task 1.1 implementation with complete Provider wiring**

In `agent_cmd.py`, replace the imports with the union of Task 1.1 imports and
these exact additions:

```python
import hashlib
import os
import signal
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone

from skillify.agent.events import EventType, TaskState
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec, TaskSpec
from skillify.agent.providers.opencode import OpenCodeError, OpenCodeProvider, ProviderCrashed, ProviderTimeout
```

Replace `_run_local_task` completely and add `_build_provider`:

```python
def _build_provider() -> OpenCodeProvider:
    return OpenCodeProvider()


def _runtime_config(config: AgentLocalConfig) -> ModelRuntimeConfig:
    if not all((config.model_endpoint, config.model_provider, config.model_name,
                config.allowed_model_hosts, config.credential_env_names)):
        raise AgentCommandFailure(AgentErrorCode.CONFIG_INVALID, "model runtime config is incomplete")
    return ModelRuntimeConfig(
        provider=config.model_provider,
        endpoint=config.model_endpoint,
        model=config.model_name,
        allowed_endpoint_hosts=config.allowed_model_hosts,
        credential_env_names=config.credential_env_names,
    )


def _run_local_task(workspace: Path, prompt: str, paths: AgentPaths,
                    config: AgentLocalConfig) -> str:
    provider = _build_provider(); handle = None; session = None
    terminal = "failed"; task_id = uuid.uuid4().hex
    config_dir = paths.cache_dir / "opencode" / hashlib.sha256(str(workspace).encode()).hexdigest()
    start_spec = ProviderStartSpec(
        workspace=workspace, allowed_paths=(workspace,), config_dir=config_dir,
        runtime=_runtime_config(config),
    )
    try:
        append_agent_log(paths, "run.start", task_id=task_id, state="starting")
        handle = provider.start(start_spec)
        session = provider.create_session(handle, TaskSpec(task_id=task_id, prompt=prompt))
        owned = provider.ownership(handle)
        write_runtime_state(paths, AgentRuntimeState(
            schema_version=1, owner_uid=os.getuid(), pid=owned["pid"], pgid=owned["pgid"],
            process_start_token=owned["start_token"], executable=owned["executable"],
            workspace_hash=hashlib.sha256(str(workspace).encode()).hexdigest(),
            task_id=task_id, session_id=session.session_id, provider_version=handle.provider_version,
            started_at=datetime.now(timezone.utc).isoformat(), state="running",
        ))
        for event in provider.stream_events(handle, session):
            reason = event.details.get("reason_code")
            append_agent_log(paths, "provider.event", task_id=event.task_id,
                             session_id=event.session_id, provider_version=event.provider_version,
                             state=event.state.value, reason_code=str(reason) if reason else "")
            if event.type is EventType.TASK_FINISHED: terminal = event.state.value
            elif event.type is EventType.TASK_BLOCKED: terminal = "blocked"
        return terminal
    except KeyboardInterrupt:
        terminal = "cancelled"; return terminal
    except Exception as exc:
        append_agent_log(paths, "run.error", task_id=task_id, state="failed", reason_code=type(exc).__name__)
        raise AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider execution failed") from exc
    finally:
        if handle is not None and session is not None:
            try: provider.cancel(handle, session)
            except Exception: append_agent_log(paths, "abort.error", task_id=task_id, state=terminal, reason_code="ABORT_FAILED")
        if handle is not None:
            try: provider.stop(handle)
            except Exception: append_agent_log(paths, "stop.error", task_id=task_id, state=terminal, reason_code="STOP_FAILED")
        paths.runtime_path.unlink(missing_ok=True)
        append_agent_log(paths, "run.stop", task_id=task_id, state=terminal)
```

Replace the Task 1.1 call site inside `run()` with:

```python
        paths, config = _config()
        resolved = _workspace(workspace, config)
        result = _run_local_task(resolved, _read_prompt(prompt_file), paths, config)
```

Update the two Task 1.1 error-path fakes in `tests/test_cli_agent.py` for the
final four-argument boundary:

```diff
-                lambda workspace, prompt: (_ for _ in ()).throw(
+                lambda workspace, prompt, paths, config: (_ for _ in ()).throw(
                     AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider start failed")
                 ),
@@
-            monkeypatch.setattr(agent_cmd, "_run_local_task", lambda workspace, prompt: "failed")
+            monkeypatch.setattr(agent_cmd, "_run_local_task", lambda workspace, prompt, paths, config: "failed")
```

- [ ] **Step 7: Add the default-skipped real smoke test**

Create `tests/test_opencode_provider_smoke.py` with this complete test:

```python
from __future__ import annotations

import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec, TaskSpec
from skillify.agent.providers.opencode import OpenCodeProvider

pytestmark = pytest.mark.skip(reason="requires test-env: real OpenCode binary, model endpoint, and target Linux")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_real_opencode_is_localhost_only_and_leaves_no_process(tmp_path: Path) -> None:
    workspace = (tmp_path / "repo").resolve(); workspace.mkdir()
    subprocess.run(["git", "init", str(workspace)], check=True, capture_output=True)
    runtime = ModelRuntimeConfig(
        provider=os.environ["TEST_OPENCODE_PROVIDER"],
        endpoint=os.environ["TEST_OPENCODE_MODEL_ENDPOINT"],
        model=os.environ["TEST_OPENCODE_MODEL"],
        allowed_endpoint_hosts=(os.environ["TEST_OPENCODE_MODEL_HOST"],),
        credential_env_names=(os.environ["TEST_OPENCODE_CREDENTIAL_ENV"],),
    )
    provider = OpenCodeProvider(
        port_factory=_free_port,
        clock=lambda: datetime.now(timezone.utc),
    )
    handle = provider.start(ProviderStartSpec(workspace, (workspace,), tmp_path / "config", runtime))
    try:
        session = provider.create_session(handle, TaskSpec("smoke-1", "Inspect README, create marker.txt, and run the repository test command."))
        events = list(provider.stream_events(handle, session))
        assert events[-1].state.value == "succeeded"
        listeners = subprocess.run(["ss", "-ltnp"], check=True, capture_output=True, text=True).stdout
        owned = [line for line in listeners.splitlines() if f"pid={handle.process_id}," in line]
        assert owned and all("127.0.0.1:" in line and "0.0.0.0:" not in line for line in owned)
    finally:
        provider.stop(handle)
    with pytest.raises(ProcessLookupError):
        os.kill(handle.process_id, 0)
```

- [ ] **Step 8: Run Task 1.3 GREEN tests and Dev-DoD**

Run:

```bash
uv run --no-sync python -m compileall -q src
uv run --no-sync pytest tests/test_provider_contract.py tests/test_opencode_provider_contract.py tests/test_opencode_provider_smoke.py -q
```

Expected: compileall exits 0; all offline tests pass; exactly the real smoke module is skipped with `requires test-env:`.

- [ ] **Step 9: Commit Task 1.3**

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

- [ ] **Step 1: Create the complete failing distribution test file**

Create `tests/test_opencode_distribution.py`:

```python
from __future__ import annotations

import hashlib, json
from pathlib import Path

import pytest

from skillify.install.opencode_distribution import (
    ArtifactCorrupt, ManifestInvalid, load_manifest, select_artifact,
    validate_manifest, verify_artifact,
)

MANIFEST = Path("infra/offline/opencode-manifest.json")


def _data(uri="file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64.tar.gz"):
    return {"schemaVersion": 1, "opencodeVersion": "1.15.11", "skillctlVersion": "0.1.0", "artifacts": [{
        "version": "1.15.11", "skillctlVersion": "0.1.0", "os": "linux", "arch": "x86_64",
        "libc": "glibc", "cpu": "avx2", "sha256": "a" * 64, "license": "MIT",
        "sourceUrl": "https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-x64.tar.gz",
        "intranetUri": uri,
    }]}


def test_repository_manifest_matches_schema_and_has_no_latest() -> None:
    data = load_manifest(MANIFEST); validate_manifest(data)
    assert "latest" not in json.dumps(data).lower()
    assert len(data["artifacts"]) == 6


def test_selects_only_exact_version_and_platform() -> None:
    artifact = select_artifact(_data(), version="1.15.11", os_name="linux", arch="x86_64", libc="glibc", cpu="avx2")
    assert artifact.version == "1.15.11" and artifact.intranet_uri.startswith("file:///")
    with pytest.raises(ManifestInvalid, match="no exact artifact"):
        select_artifact(_data(), version="1.15.12", os_name="linux", arch="x86_64", libc="glibc", cpu="avx2")


@pytest.mark.parametrize("uri", ["https://mirror.example/opencode.tgz", "forgejo://artifacts/opencode.tgz", "file://host/path.tgz", "file:relative.tgz"])
def test_rejects_every_non_local_or_non_absolute_runtime_uri(uri: str) -> None:
    with pytest.raises(ManifestInvalid, match="intranetUri"):
        validate_manifest(_data(uri))


def test_verifies_matching_sha256_and_rejects_corruption(tmp_path: Path) -> None:
    path = tmp_path / "opencode.tar.gz"; path.write_bytes(b"official bytes")
    data = _data(); data["artifacts"][0]["sha256"] = hashlib.sha256(b"official bytes").hexdigest()
    artifact = select_artifact(data, version="1.15.11", os_name="linux", arch="x86_64", libc="glibc", cpu="avx2")
    verify_artifact(path, artifact)
    path.write_bytes(b"corrupt")
    with pytest.raises(ArtifactCorrupt): verify_artifact(path, artifact)
```

- [ ] **Step 2: Run Task 1.4 RED tests**

Run:

```bash
uv run --no-sync pytest tests/test_opencode_distribution.py -q
```

Expected: import failure for `skillify.install.opencode_distribution` and missing repository manifest.

- [ ] **Step 3: Create the complete strict manifest implementation**

Create `src/skillify/install/opencode_distribution.py`:

```python
from __future__ import annotations

import hmac, json, re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from skillify.install.extract import sha256_file


class DistributionError(Exception): pass
class ManifestInvalid(DistributionError): pass
class ArtifactNotFound(DistributionError): pass
class ArtifactCorrupt(DistributionError): pass


@dataclass(frozen=True)
class OpenCodeArtifact:
    version: str; skillctl_version: str; os: str; arch: str; libc: str; cpu: str
    sha256: str; license: str; source_url: str; intranet_uri: str


_ARTIFACT_REQUIRED = ["version", "skillctlVersion", "os", "arch", "libc", "cpu", "sha256", "license", "sourceUrl", "intranetUri"]
MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["schemaVersion", "opencodeVersion", "skillctlVersion", "artifacts"],
    "properties": {
        "schemaVersion": {"const": 1}, "opencodeVersion": {"const": "1.15.11"},
        "skillctlVersion": {"const": "0.1.0"},
        "artifacts": {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
            "required": _ARTIFACT_REQUIRED, "properties": {
                "version": {"const": "1.15.11"}, "skillctlVersion": {"const": "0.1.0"},
                "os": {"const": "linux"}, "arch": {"enum": ["x86_64", "aarch64"]},
                "libc": {"enum": ["glibc", "musl"]}, "cpu": {"enum": ["avx2", "baseline", "arm64"]},
                "sha256": {"pattern": "^[0-9a-f]{64}$"}, "license": {"const": "MIT"},
                "sourceUrl": {"type": "string"}, "intranetUri": {"type": "string"},
            }}},
    },
}


def load_manifest(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ManifestInvalid("manifest must be an object")
    return value


def validate_manifest(data: Mapping[str, object]) -> None:
    errors = sorted(Draft202012Validator(MANIFEST_SCHEMA).iter_errors(data), key=lambda error: list(error.path))
    if errors: raise ManifestInvalid(errors[0].message)
    if "latest" in json.dumps(data).lower(): raise ManifestInvalid("floating latest is forbidden")
    seen = set()
    for item in data["artifacts"]:
        source = urlsplit(item["sourceUrl"]); runtime = urlsplit(item["intranetUri"])
        if source.scheme != "https" or source.hostname != "github.com" or "/releases/download/v1.15.11/" not in source.path:
            raise ManifestInvalid("sourceUrl must be the pinned official GitHub release")
        if runtime.scheme != "file" or runtime.netloc or not runtime.path.startswith("/opt/skillify/offline/opencode/v1.15.11/"):
            raise ManifestInvalid("intranetUri must be an absolute local file: bundle URI")
        key = tuple(item[name] for name in ("version", "os", "arch", "libc", "cpu"))
        if key in seen: raise ManifestInvalid("duplicate artifact selector")
        seen.add(key)


def select_artifact(data, *, version, os_name, arch, libc, cpu):
    validate_manifest(data)
    matches = [item for item in data["artifacts"] if (item["version"], item["os"], item["arch"], item["libc"], item["cpu"]) == (version, os_name, arch, libc, cpu)]
    if len(matches) != 1: raise ManifestInvalid("no exact artifact for version and platform")
    item = matches[0]
    return OpenCodeArtifact(item["version"], item["skillctlVersion"], item["os"], item["arch"], item["libc"], item["cpu"], item["sha256"], item["license"], item["sourceUrl"], item["intranetUri"])


def verify_artifact(path: Path, artifact: OpenCodeArtifact) -> None:
    if not hmac.compare_digest(sha256_file(path), artifact.sha256):
        raise ArtifactCorrupt(f"{path}: OpenCode artifact checksum mismatch")
```

- [ ] **Step 4: Create the canonical v1.15.11 manifest**

Create `infra/offline/opencode-manifest.json` with this complete content:

```json
{
  "schemaVersion": 1,
  "opencodeVersion": "1.15.11",
  "skillctlVersion": "0.1.0",
  "artifacts": [
    {
      "version": "1.15.11", "skillctlVersion": "0.1.0", "os": "linux", "arch": "x86_64", "libc": "glibc", "cpu": "avx2",
      "sha256": "49317253722c698394980e1921ff28e919d79bb29d5c3f4cf314a4adaf7037cd", "license": "MIT",
      "sourceUrl": "https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-x64.tar.gz",
      "intranetUri": "file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64.tar.gz"
    },
    {
      "version": "1.15.11", "skillctlVersion": "0.1.0", "os": "linux", "arch": "x86_64", "libc": "glibc", "cpu": "baseline",
      "sha256": "eb19eabc9cb7fa8a73898328b69720738d35e0cad716898bfdbc2547f88b2450", "license": "MIT",
      "sourceUrl": "https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-x64-baseline.tar.gz",
      "intranetUri": "file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64-baseline.tar.gz"
    },
    {
      "version": "1.15.11", "skillctlVersion": "0.1.0", "os": "linux", "arch": "x86_64", "libc": "musl", "cpu": "avx2",
      "sha256": "82fdc56334a02fd89b123643197b59bea2af829be13f82ec154f210053423207", "license": "MIT",
      "sourceUrl": "https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-x64-musl.tar.gz",
      "intranetUri": "file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64-musl.tar.gz"
    },
    {
      "version": "1.15.11", "skillctlVersion": "0.1.0", "os": "linux", "arch": "x86_64", "libc": "musl", "cpu": "baseline",
      "sha256": "421a63ecc5ae66b87b150349f29477a952a01526e85b48783bccce4c7b8dabd9", "license": "MIT",
      "sourceUrl": "https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-x64-baseline-musl.tar.gz",
      "intranetUri": "file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64-baseline-musl.tar.gz"
    },
    {
      "version": "1.15.11", "skillctlVersion": "0.1.0", "os": "linux", "arch": "aarch64", "libc": "glibc", "cpu": "arm64",
      "sha256": "93e4399f308c49387c25ec2b570602bf0f9dd5f57989427946c0c28dbf259ff4", "license": "MIT",
      "sourceUrl": "https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-arm64.tar.gz",
      "intranetUri": "file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-arm64.tar.gz"
    },
    {
      "version": "1.15.11", "skillctlVersion": "0.1.0", "os": "linux", "arch": "aarch64", "libc": "musl", "cpu": "arm64",
      "sha256": "871b80411bd670ed9372335f0658203557fa4bfbf7791a3b1ab1d1f641103448", "license": "MIT",
      "sourceUrl": "https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-arm64-musl.tar.gz",
      "intranetUri": "file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-arm64-musl.tar.gz"
    }
  ]
}
```

- [ ] **Step 5: Add the complete manifest-driven doctor check**

First append this doctor-specific RED test to `tests/test_opencode_distribution.py`:

```python
def test_doctor_verifies_manifest_platform_version_and_checksum(tmp_path: Path) -> None:
    from skillify.cli.doctor_cmd import _check_opencode_distribution
    payload = b"approved opencode bundle"
    data = _data(); data["artifacts"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps(data), encoding="utf-8")
    artifact_root = tmp_path / "artifacts"; artifact_root.mkdir()
    (artifact_root / "opencode-linux-x64.tar.gz").write_bytes(payload)
    checks = _check_opencode_distribution(
        manifest_path=manifest,
        artifact_root=artifact_root,
        platform_detector=lambda: ("linux", "x86_64", "glibc", "avx2"),
        version_runner=lambda argv: "1.15.11\n",
    )
    assert [check.name for check in checks] == [
        "opencode-manifest", "opencode-platform", "opencode-version", "opencode-checksum",
    ]
    assert all(check.ok for check in checks)
```

Run `uv run --no-sync pytest tests/test_opencode_distribution.py -q`; expected:
`ImportError: cannot import name '_check_opencode_distribution'`.

Then add these imports to `doctor_cmd.py`:

```python
import os
import platform
import subprocess
from urllib.parse import urlsplit

from skillify.common.config import (
    SkillifyConfig, load_agent_local_config, load_agent_paths, load_config,
)
from skillify.install.opencode_distribution import (
    DistributionError, load_manifest, select_artifact, verify_artifact,
)
```

Add the complete detector, runner, configuration resolver, and check. No function
in this block downloads an artifact:

```python
def _detect_opencode_platform() -> tuple[str, str, str, str]:
    if sys.platform != "linux": raise ValueError("OpenCode S1 supports Linux only")
    machine = platform.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine)
    if arch is None: raise ValueError(f"unsupported architecture: {machine}")
    libc_name = platform.libc_ver()[0].lower()
    libc = "musl" if "musl" in libc_name else "glibc" if "glibc" in libc_name else ""
    if not libc: raise ValueError("unable to detect glibc or musl")
    if arch == "aarch64": return "linux", arch, libc, "arm64"
    flags = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").lower()
    return "linux", arch, libc, "avx2" if " avx2" in flags else "baseline"


def _opencode_version(argv: list[str]) -> str:
    completed = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=5)
    return completed.stdout


def _opencode_distribution_paths() -> tuple[Path, Path]:
    local = load_agent_local_config(load_agent_paths())
    manifest = os.environ.get("SKILLIFY_OPENCODE_MANIFEST_PATH") or local.opencode_manifest_path
    artifacts = os.environ.get("SKILLIFY_OPENCODE_ARTIFACT_ROOT") or local.opencode_artifact_root
    if not manifest: raise ValueError("SKILLIFY_OPENCODE_MANIFEST_PATH or opencode_manifest_path is required")
    if not artifacts: raise ValueError("SKILLIFY_OPENCODE_ARTIFACT_ROOT or opencode_artifact_root is required")
    return Path(manifest).expanduser().resolve(), Path(artifacts).expanduser().resolve()


def _check_opencode_distribution(*, manifest_path: Path, artifact_root: Path,
                                 platform_detector=_detect_opencode_platform,
                                 version_runner=_opencode_version) -> list[CheckResult]:
    try:
        os_name, arch, libc, cpu = platform_detector()
        data = load_manifest(manifest_path)
        artifact = select_artifact(data, version="1.15.11", os_name=os_name, arch=arch, libc=libc, cpu=cpu)
        local_path = artifact_root / Path(urlsplit(artifact.intranet_uri).path).name
        verify_artifact(local_path, artifact)
        actual = version_runner(["opencode", "--version"])
        if actual.strip() != artifact.version:
            return [CheckResult("opencode-version", False, f"expected {artifact.version}, got {actual.strip()}")]
        return [
            CheckResult("opencode-manifest", True, str(manifest_path)),
            CheckResult("opencode-platform", True, f"{os_name}/{arch}/{libc}/{cpu}"),
            CheckResult("opencode-version", True, artifact.version),
            CheckResult("opencode-checksum", True, artifact.sha256),
        ]
    except (OSError, DistributionError, ValueError) as exc:
        return [CheckResult("opencode-manifest", False, str(exc), "install the approved offline bundle")]
```

Finally, insert this exact call site in `run_doctor()` immediately after
`checks += [_check_binary(b) for b in REQUIRED_BINARIES]`; all existing checks
below it remain unchanged:

```python
    try:
        manifest_path, artifact_root = _opencode_distribution_paths()
        checks += _check_opencode_distribution(
            manifest_path=manifest_path,
            artifact_root=artifact_root,
        )
    except (OSError, ValueError) as exc:
        checks.append(CheckResult(
            "opencode-manifest", False, str(exc), "configure the approved offline OpenCode bundle",
        ))
```

Run `uv run --no-sync pytest tests/test_opencode_distribution.py -q`; expected:
all tests pass, with no network calls.

- [ ] **Step 6: Write the offline deployment runbook**

Create `docs/deployment/offline-opencode.md` with this complete content:

````markdown
# Offline OpenCode v1.15.11 deployment

This procedure installs the S1-approved OpenCode v1.15.11 binary on disconnected
Linux endpoints. Runtime public downloads are prohibited. The six approved
source URLs, platform selectors, immutable local bundle URIs, and SHA-256 values
are exactly those in `infra/offline/opencode-manifest.json`.

## Stage and approve the bundle

On an internet-connected staging host, select the manifest entry matching the
target's architecture, libc, and CPU. For an x86-64 glibc host without AVX2:

```bash
mkdir -p /var/tmp/opencode-1.15.11
cd /var/tmp/opencode-1.15.11
curl -fL --proto '=https' --tlsv1.2 \
  -o opencode-linux-x64-baseline.tar.gz \
  https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-x64-baseline.tar.gz
printf '%s  %s\n' \
  eb19eabc9cb7fa8a73898328b69720738d35e0cad716898bfdbc2547f88b2450 \
  opencode-linux-x64-baseline.tar.gz | sha256sum --check --strict
sha256sum opencode-linux-x64-baseline.tar.gz
```

The check output and independently recomputed digest must both equal
`eb19eabc9cb7fa8a73898328b69720738d35e0cad716898bfdbc2547f88b2450`.
Perform malware scanning and OSS/security approval, retain the upstream MIT
license notice beside the bundle, and record approver, scanner version, scan
result, source URL, and digest. Publish the approved bytes to immutable internal
storage without renaming them. Copy the repository manifest unchanged beside
the bundle set. Never publish a mutable `latest` alias.

## Transfer and disconnected install

Transfer the approved directory through the controlled media gateway to
`/opt/skillify/offline/opencode/v1.15.11/`. Before extracting, run the same
`sha256sum --check --strict` command using the selected manifest digest. A
failure stops installation.

```bash
install -d -m 0755 /opt/skillify/opencode/1.15.11/bin
tar -xzf /opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64-baseline.tar.gz \
  -C /opt/skillify/opencode/1.15.11/bin
/opt/skillify/opencode/1.15.11/bin/opencode --version
ln -sfn /opt/skillify/opencode/1.15.11 /opt/skillify/opencode/current
ln -sfn /opt/skillify/opencode/current/bin/opencode /usr/local/bin/opencode
```

The version command must print `1.15.11`. Configure doctor with absolute local
paths only:

```bash
export SKILLIFY_OPENCODE_MANIFEST_PATH=/opt/skillify/offline/opencode/opencode-manifest.json
export SKILLIFY_OPENCODE_ARTIFACT_ROOT=/opt/skillify/offline/opencode/v1.15.11
```

## Endpoint configuration

In the endpoint agent YAML, set `model_endpoint` to the approved internal HTTPS
endpoint, `model_provider` and `model_name` to approved identifiers,
`allowed_model_hosts` to that endpoint's exact host, and
`credential_env_names` to the approved secret variable name. Store the secret
value in the endpoint secret manager/environment, never in YAML or logs.

The launcher must set:

```bash
export OPENCODE_DISABLE_AUTOUPDATE=true
export OPENCODE_DISABLE_LSP_DOWNLOAD=true
export OPENCODE_DISABLE_DEFAULT_PLUGINS=true
export NO_PROXY=localhost,127.0.0.1
```

OpenCode must bind `127.0.0.1` only. Firewall policy must deny endpoint inbound
access and permit only the approved outbound model/MCP destinations.

## Upgrade, downgrade, and rollback

Stage every new version as a separate immutable directory and reviewed manifest;
do not overwrite v1.15.11. Stop the agent, verify no owned process remains,
install and verify the new version, atomically repoint `current`, then rerun the
acceptance checklist. To downgrade or roll back, stop the agent, repoint
`/opt/skillify/opencode/current` to the previously approved directory, verify its
manifest checksum and version, and rerun the checklist. Preserve failed-version
logs and approval evidence; never bypass an incompatible libc/CPU selector.

## `[test-env]` acceptance evidence

On the disconnected target, record OS, architecture, libc, and CPU flags, then run:

```bash
uname -a
getconf GNU_LIBC_VERSION || ldd --version
grep -m1 -E '^(flags|Features)' /proc/cpuinfo
opencode --version
skillctl agent doctor --format json
skillctl agent run --workspace /srv/skillify-test/repository \
  --prompt-file /srv/skillify-test/task.txt --format json
ss -ltnp
ps -ef | grep '[o]pencode serve'
skillctl agent stop --format json
ps -ef | grep '[o]pencode serve'
```

Retain evidence that doctor reports the exact manifest/platform/version/checksum,
the example task produced the expected edit/test/diff summary, every OpenCode
listener is on `127.0.0.1`, cancellation and SIGTERM complete within their bounds,
and the final process query has no OpenCode server. Any failure blocks G1.
````

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
