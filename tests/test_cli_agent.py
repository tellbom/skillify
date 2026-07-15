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


def test_stop_maps_runtime_unlink_oserror_to_config_invalid(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "state/runtime.json").mkdir(parents=True)

    result = runner.invoke(agent_app, ["stop", "--format", "json"], env=env)
    _assert_error_envelope(result, exit_code=10, code="AGENT_CONFIG_INVALID")
