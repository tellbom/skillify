from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
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


def _assert_error_envelope(result, *, exit_code: int, code: str) -> None:
    assert result.exit_code == exit_code
    payload = _json(result)
    assert payload["ok"] is False
    assert payload["code"] == code
    assert set(payload) == {"ok", "code", "message", "data"}
    assert payload["data"] == {}


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
    config = yaml.safe_load(text)
    assert config["allowed_workspaces"] == [str(workspace.resolve())]
    assert str(tmp_path.parent) not in config["allowed_workspaces"]


def test_agent_init_rejects_nonexistent_workspace_with_json_envelope(tmp_path: Path) -> None:
    result = runner.invoke(
        agent_app,
        ["init", "--workspace", str(tmp_path / "missing"), "--format", "json"],
        env=_env(tmp_path),
    )
    _assert_error_envelope(
        result,
        exit_code=11,
        code="AGENT_WORKSPACE_UNAUTHORIZED",
    )


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


def test_agent_run_maps_missing_prompt_to_config_invalid(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    env = _env(tmp_path)
    assert runner.invoke(
        agent_app,
        ["init", "--workspace", str(workspace), "--format", "json"],
        env=env,
    ).exit_code == 0

    result = runner.invoke(
        agent_app,
        [
            "run",
            "--workspace",
            str(workspace),
            "--prompt-file",
            str(tmp_path / "missing-prompt.txt"),
            "--format",
            "json",
        ],
        env=env,
    )
    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")


def test_agent_init_maps_config_save_oserror_to_config_invalid(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    config_path = tmp_path / "config-is-a-file"
    config_path.write_text("not a directory", encoding="utf-8")
    env = _env(tmp_path)
    env["SKILLIFY_AGENT_CONFIG_DIR"] = str(config_path)

    result = runner.invoke(
        agent_app,
        ["init", "--workspace", str(workspace), "--format", "json"],
        env=env,
    )
    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")


def test_status_rejects_config_yaml_directory(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "config/config.yaml").mkdir(parents=True)

    result = runner.invoke(agent_app, ["status", "--format", "json"], env=env)
    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")


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
                lambda workspace, prompt, paths, config: (_ for _ in ()).throw(
                    AgentCommandFailure(AgentErrorCode.PROVIDER_FAILED, "provider start failed")
                ),
            )
        if case == "task":
            monkeypatch.setattr(agent_cmd, "_run_local_task", lambda workspace, prompt, paths, config: "failed")
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


@pytest.mark.parametrize("identity_valid", [True, False])
def test_status_keeps_runtime_and_reports_degraded_for_nonempty_owned_or_uncertain_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity_valid: bool
) -> None:
    from skillify.cli.agent_cmd import AgentRuntimeState, write_runtime_state

    env = _env(tmp_path); paths = load_agent_paths(env, home=tmp_path)
    state = AgentRuntimeState(
        1, __import__("os").getuid(), 4242, 4242, 4242, "100",
        "/opt/skillify/opencode", "workspace", "task-1", "session-1", "1.15.11",
        "2026-07-16T00:00:00+00:00", "running",
    )
    write_runtime_state(paths, state)
    child = type("Member", (), {
        "pid": 5000, "pgid": 4242, "sid": 4242,
        "uid": state.owner_uid, "start_token": "101",
    })()
    class Inspector:
        def is_alive(self, pid): return not identity_valid
        def pgid(self, pid): return 9999
        def session_id(self, pid): return 4242
        def start_token(self, pid): return "reused"
        def uid(self, pid): return state.owner_uid
        def executable(self, pid): return state.executable
        def group_members(self, pgid): return (child,)
    monkeypatch.setattr(agent_cmd, "LinuxProcessInspector", lambda: Inspector())

    result = runner.invoke(agent_app, ["status", "--format", "json"], env=env)
    assert result.exit_code == 0
    assert _json(result)["data"] == {
        "state": "degraded", "task_id": "task-1", "session_id": "session-1",
    }
    assert paths.runtime_path.exists()


def test_status_deletes_runtime_only_after_whole_group_is_confirmed_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skillify.cli.agent_cmd import AgentRuntimeState, write_runtime_state

    env = _env(tmp_path); paths = load_agent_paths(env, home=tmp_path)
    write_runtime_state(paths, AgentRuntimeState(
        1, __import__("os").getuid(), 4242, 4242, 4242, "100",
        "/opt/skillify/opencode", "workspace", "task-1", "session-1", "1.15.11",
        "2026-07-16T00:00:00+00:00", "running",
    ))
    class EmptyInspector:
        def is_alive(self, pid): return False
        def group_members(self, pgid): return ()
    monkeypatch.setattr(agent_cmd, "LinuxProcessInspector", lambda: EmptyInspector())

    result = runner.invoke(agent_app, ["status", "--format", "json"], env=env)
    assert _json(result)["data"] == {"state": "stopped"}
    assert not paths.runtime_path.exists()


@pytest.mark.parametrize(
    "runtime_data",
    [
        [],
        None,
        "running",
        1,
        {"state": ""},
        {"state": 1},
    ],
)
def test_status_rejects_non_mapping_or_invalid_runtime_state(
    tmp_path: Path,
    runtime_data: object,
) -> None:
    env = _env(tmp_path)
    runtime_path = tmp_path / "state/runtime.json"
    runtime_path.parent.mkdir()
    runtime_path.write_text(json.dumps(runtime_data), encoding="utf-8")

    result = runner.invoke(agent_app, ["status", "--format", "json"], env=env)
    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")


def test_status_rejects_runtime_json_directory(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "state/runtime.json").mkdir(parents=True)

    result = runner.invoke(agent_app, ["status", "--format", "json"], env=env)
    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")


def test_logs_maps_read_oserror_to_config_invalid(tmp_path: Path) -> None:
    env = _env(tmp_path)
    log_path = tmp_path / "log/agent.log"
    log_path.parent.mkdir()
    log_path.write_text("private lifecycle line\n", encoding="utf-8")
    log_path.chmod(0o000)
    try:
        result = runner.invoke(agent_app, ["logs", "--format", "json"], env=env)
    finally:
        log_path.chmod(0o600)

    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")


def test_logs_rejects_agent_log_directory(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "log/agent.log").mkdir(parents=True)

    result = runner.invoke(agent_app, ["logs", "--format", "json"], env=env)
    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")


def test_stop_maps_runtime_unlink_oserror_to_config_invalid(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "state/runtime.json").mkdir(parents=True)

    result = runner.invoke(agent_app, ["stop", "--format", "json"], env=env)
    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")


def test_invalid_runtime_endpoint_maps_to_config_invalid(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"; workspace.mkdir(); env = _env(tmp_path)
    initialized = runner.invoke(agent_app, [
        "init", "--workspace", str(workspace),
        "--model-endpoint", "https://unapproved.example/v1",
        "--model-provider", "internal", "--model", "code-1",
        "--allowed-model-host", "model.intranet.example",
        "--credential-env", "MODEL_KEY", "--format", "json",
    ], env=env)
    assert initialized.exit_code == 0
    result = runner.invoke(
        agent_app, ["run", "--workspace", str(workspace), "--prompt-file", "-", "--format", "json"],
        input="inspect\n", env=env,
    )
    assert result.exit_code == 10
    assert _json(result) == {
        "ok": False, "code": "AGENT_CONFIG_INVALID",
        "message": "model runtime config is invalid", "data": {},
    }


@pytest.mark.parametrize("changes", [
    {"model_endpoint": None},
    {"model_endpoint": "ftp://model.intranet.example/v1"},
    {"allowed_model_hosts": ()},
    {"allowed_model_hosts": ("other.intranet.example",)},
    {"credential_env_names": ()},
    {"credential_env_names": ("bad-name",)},
])
def test_all_invalid_or_missing_runtime_fields_map_to_config_invalid(changes) -> None:
    from dataclasses import replace
    from skillify.cli.agent_cmd import AgentCommandFailure, _runtime_config
    from skillify.common.config import AgentLocalConfig
    base = AgentLocalConfig(
        model_endpoint="https://model.intranet.example/v1", model_provider="internal",
        model_name="code-1", allowed_model_hosts=("model.intranet.example",),
        credential_env_names=("MODEL_KEY",),
    )
    with pytest.raises(AgentCommandFailure) as captured:
        _runtime_config(replace(base, **changes))
    assert captured.value.code is AgentErrorCode.CONFIG_INVALID


def test_malformed_missing_and_wrong_type_runtime_json_have_stable_envelopes(tmp_path: Path) -> None:
    env = _env(tmp_path); runtime = tmp_path / "state/runtime.json"; runtime.parent.mkdir()
    complete = {
        "schema_version": 1, "owner_uid": 1000, "pid": 4242, "pgid": 4242,
        "process_session_id": 4242,
        "process_start_token": "start", "executable": "opencode", "workspace_hash": "hash",
        "task_id": "task", "session_id": "session", "provider_version": "1.15.11",
        "started_at": "2026-07-16T00:00:00+00:00", "state": "running",
    }
    payloads = ["{", "{}", json.dumps({**complete, "pid": "4242"})]
    for command in ("status", "stop"):
        for payload in payloads:
            runtime.write_text(payload, encoding="utf-8")
            result = runner.invoke(agent_app, [command, "--format", "json"], env=env)
            assert result.exit_code == 10
            assert _json(result) == {
                "ok": False, "code": "AGENT_CONFIG_INVALID",
                "message": "runtime state is invalid", "data": {},
            }


def test_stop_unconfirmed_returns_provider_failed_envelope(tmp_path: Path, monkeypatch) -> None:
    from skillify.cli import agent_cmd
    env = _env(tmp_path)
    monkeypatch.setattr(agent_cmd, "stop_owned_process", lambda paths, inspector: False)
    result = runner.invoke(agent_app, ["stop", "--format", "json"], env=env)
    assert result.exit_code == 13
    assert _json(result) == {
        "ok": False, "code": "AGENT_PROVIDER_FAILED",
        "message": "provider stop was not confirmed", "data": {},
    }


def test_cleanup_pending_runtime_write_failure_stops_restores_and_has_stable_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signal
    from skillify.agent.provider import ProviderHandle, ProviderResult
    from skillify.agent.events import TaskState
    from skillify.agent.providers.opencode import ProviderCleanupPending
    from skillify.common.config import AgentLocalConfig

    paths = load_agent_paths(_env(tmp_path), home=tmp_path)
    workspace = (tmp_path / "repo").resolve(); workspace.mkdir()
    config = AgentLocalConfig(
        allowed_workspaces=(str(workspace),),
        model_endpoint="https://model.intranet.example/v1",
        model_provider="internal", model_name="code-1",
        allowed_model_hosts=("model.intranet.example",),
        credential_env_names=("MODEL_KEY",),
    )
    handle = ProviderHandle(
        "pending", "opencode", "unknown", "http://127.0.0.1:32123", 4242,
    )
    calls = []; installed = []; previous = object()
    class PendingProvider:
        def start(self, spec):
            calls.append("start"); raise ProviderCleanupPending(handle)
        def ownership(self, value):
            calls.append("ownership")
            return {"pid": 4242, "pgid": 4242, "sid": 4242, "start_token": "100",
                    "uid": __import__("os").getuid(), "executable": "/opt/skillify/opencode"}
        def stop(self, value):
            calls.append("stop"); return ProviderResult(TaskState.SUCCEEDED)

    monkeypatch.setenv("MODEL_KEY", "top-secret")
    monkeypatch.setattr(agent_cmd, "_config", lambda: (paths, config))
    monkeypatch.setattr(agent_cmd, "_build_provider", lambda: PendingProvider())
    monkeypatch.setattr(
        agent_cmd, "write_runtime_state",
        lambda paths, state: (_ for _ in ()).throw(OSError("private state detail")),
    )
    monkeypatch.setattr(agent_cmd.signal, "getsignal", lambda sig: previous)
    monkeypatch.setattr(agent_cmd.signal, "signal", lambda sig, handler: installed.append(handler))

    result = runner.invoke(
        agent_app,
        ["run", "--workspace", str(workspace), "--prompt-file", "-", "--format", "json"],
        input="private prompt\n",
    )
    _assert_error_envelope(result, exit_code=13, code="AGENT_PROVIDER_FAILED")
    assert calls == ["start", "ownership", "stop"]
    assert installed[-1] is previous
    assert "private state detail" not in result.stdout
    assert not paths.runtime_path.exists()


def test_status_maps_process_inspection_oserror_to_config_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = agent_cmd.AgentRuntimeState(
        1, __import__("os").getuid(), 4242, 4242, 4242, "start", "/opt/skillify/opencode",
        "workspace", "task", "session", "1.15.11", "time", "running",
    )
    monkeypatch.setattr(agent_cmd, "read_runtime_state", lambda paths: state)
    monkeypatch.setattr(
        agent_cmd,
        "_confirmed_owned_group",
        lambda state, inspector: (_ for _ in ()).throw(PermissionError("private path")),
    )
    result = runner.invoke(agent_app, ["status", "--format", "json"], env=_env(tmp_path))
    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")


def test_stop_maps_owned_state_oserror_to_config_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        agent_cmd,
        "stop_owned_process",
        lambda paths, inspector: (_ for _ in ()).throw(PermissionError("private path")),
    )
    result = runner.invoke(agent_app, ["stop", "--format", "json"], env=_env(tmp_path))
    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")


def test_agent_log_rejects_unenumerated_reason_code(tmp_path: Path) -> None:
    paths = load_agent_paths(_env(tmp_path), home=tmp_path)
    agent_cmd.append_agent_log(
        paths, "run.error", task_id="task-1", state="failed",
        reason_code="PRIVATE_REMOTE_ERROR",
    )
    text = paths.log_path.read_text(encoding="utf-8")
    assert "PRIVATE_REMOTE_ERROR" not in text
    assert json.loads(text)["event"] == "run.error"
