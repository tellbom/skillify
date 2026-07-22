from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import skillify.cli.agent_cmd as agent_cmd
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec
from skillify.agent.providers.opencode import OpenCodeError, OpenCodeProvider
from skillify.cli.agent_cmd import agent_app
from skillify.install.opencode_distribution import (
    ArtifactNotApproved, ManifestInvalid, load_manifest, select_skillctl, validate_manifest,
)


runner = CliRunner()


class FakeProcess:
    pid = 4242

    def __init__(self) -> None:
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


class Healthy:
    def request_json(self, *args, **kwargs):
        return {"healthy": True, "version": "1.15.11"}


def _runtime() -> ModelRuntimeConfig:
    return ModelRuntimeConfig(
        "internal", "https://model.intranet.example/v1", "code-1",
        ("model.intranet.example",), ("MODEL_KEY",),
    )


def _spec(tmp_path: Path, source: Path | None = None) -> ProviderStartSpec:
    workspace = (tmp_path / "repo").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return ProviderStartSpec(
        workspace, (workspace,), tmp_path / "generated", _runtime(),
        source_config_path=source,
    )


def _provider(monkeypatch, *, version_result="1.15.11\n"):
    process = FakeProcess()
    captured = {}

    def popen(argv, **kwargs):
        captured.update(argv=argv, kwargs=kwargs)
        return process

    def version_runner(argv):
        if isinstance(version_result, BaseException):
            raise version_result
        return version_result

    monkeypatch.setenv("MODEL_KEY", "private")
    monkeypatch.setattr(
        "skillify.agent.providers.opencode.shutil.which",
        lambda executable: "/opt/skillify/opencode",
    )
    provider = OpenCodeProvider(
        transport=Healthy(), popen=popen, port_factory=lambda: 32123,
        password_factory=lambda: "temporary-password", monotonic=lambda: 0.0,
        sleep=lambda value: None, killpg=lambda pgid, sig: setattr(process, "returncode", 0),
        getpgid=lambda pid: pid, process_start_token=lambda pid: "100",
        process_uid=lambda pid: __import__("os").getuid(), process_session_id=lambda pid: pid,
        process_executable=lambda pid: "/opt/skillify/opencode",
        group_members=lambda pgid: () if process.poll() is not None else (type("M", (), {
            "pid": 4242, "pgid": 4242, "sid": 4242,
            "uid": __import__("os").getuid(), "start_token": "100",
        })(),), version_runner=version_runner,
    )
    return provider, captured, process


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        ("1.15.10\n", "OPENCODE_VERSION_UNSUPPORTED"),
        (subprocess.TimeoutExpired(["opencode", "--version"], 5), "OPENCODE_PROBE_FAILED"),
        (subprocess.CalledProcessError(2, ["opencode", "--version"]), "OPENCODE_PROBE_FAILED"),
    ],
)
def test_probe_uses_real_version_and_fails_closed(result, reason, monkeypatch):
    provider, _, _ = _provider(monkeypatch, version_result=result)
    probe = provider.probe()
    assert probe.available is False
    assert probe.capability is None
    assert probe.reason_code == reason


@pytest.mark.parametrize("version_result", [
    "1.15.10\n",
    subprocess.TimeoutExpired(["/opt/skillify/opencode", "--version"], 5),
    subprocess.CalledProcessError(2, ["/opt/skillify/opencode", "--version"]),
])
def test_start_rejects_unsupported_executable_before_launch(tmp_path, monkeypatch, version_result):
    provider, captured, _ = _provider(monkeypatch, version_result=version_result)
    with pytest.raises(OpenCodeError, match="unavailable or incompatible"):
        provider.start(_spec(tmp_path))
    assert captured == {}


def test_start_rejects_mismatched_health_version_and_disables_remote_fetch(tmp_path, monkeypatch):
    class WrongHealth:
        def request_json(self, *args, **kwargs):
            return {"healthy": True, "version": "1.15.10"}

    monkeypatch.setenv("HOME", "/private/controller-home")
    provider, captured, process = _provider(monkeypatch)
    provider.transport = WrongHealth()
    with pytest.raises(OpenCodeError, match="unsupported opencode version"):
        provider.start(_spec(tmp_path))
    assert process.poll() is not None
    assert captured["argv"][0] == "/opt/skillify/opencode"
    assert captured["kwargs"]["env"]["OPENCODE_DISABLE_MODELS_FETCH"] == "true"
    assert captured["kwargs"]["env"]["HOME"] == "/private/controller-home"
    assert (tmp_path / "generated").stat().st_mode & 0o777 == 0o700


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        "SKILLIFY_AGENT_CONFIG_DIR": str(tmp_path / "config"),
        "SKILLIFY_AGENT_STATE_DIR": str(tmp_path / "state"),
        "SKILLIFY_AGENT_CACHE_DIR": str(tmp_path / "cache"),
        "SKILLIFY_AGENT_LOG_DIR": str(tmp_path / "log"),
    }


def _registered(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    env = _env(tmp_path)
    result = runner.invoke(agent_app, ["init", "--workspace", str(workspace), "--format", "json"], env=env)
    assert result.exit_code == 0
    return workspace, env


@pytest.mark.parametrize("task_value", ["literal task", "task.txt", "-"])
def test_run_canonical_task_accepts_literal_existing_file_and_stdin(tmp_path, monkeypatch, task_value):
    workspace, env = _registered(tmp_path)
    task_file = tmp_path / "task.txt"
    task_file.write_text("file task", encoding="utf-8")
    observed = []
    monkeypatch.setattr(agent_cmd, "_run_local_task", lambda workspace, prompt, paths, config: observed.append(prompt) or "succeeded")
    value = str(task_file) if task_value == "task.txt" else task_value
    result = runner.invoke(
        agent_app, ["run", "--workspace", str(workspace), "--task", value, "--format", "json"],
        input="stdin task\n" if value == "-" else None, env=env,
    )
    assert result.exit_code == 0
    assert observed == [{"literal task": "literal task", "task.txt": "file task", "-": "stdin task\n"}[task_value]]


def test_run_rejects_ambiguous_task_and_prompt_file(tmp_path):
    workspace, env = _registered(tmp_path)
    result = runner.invoke(agent_app, [
        "run", "--workspace", str(workspace), "--task", "literal",
        "--prompt-file", "-", "--format", "json",
    ], env=env)
    assert result.exit_code == 10
    assert json.loads(result.stdout)["code"] == "AGENT_CONFIG_INVALID"


def test_run_help_exposes_canonical_task_and_hides_compatibility_alias():
    result = runner.invoke(agent_app, ["run", "--help"], color=False)
    assert result.exit_code == 0
    assert "--task" in result.stdout
    assert "--prompt-file" not in result.stdout


def test_logs_filter_parsed_redacted_records_before_limit(tmp_path):
    env = _env(tmp_path)
    log = tmp_path / "log/agent.log"
    log.parent.mkdir()
    wanted = "a" * 32
    other = "b" * 32
    records = [
        {"event": "run.start", "task_id": other, "state": "starting", "prompt": "leak"},
        {"event": "run.start", "task_id": wanted, "state": "starting", "password": "leak"},
        "not-json",
        {"event": "provider.event", "task_id": wanted, "session_id": "session-1",
         "provider_version": "1.15.11", "state": "running", "source": "leak"},
        {"event": "attacker.event", "task_id": wanted, "state": "running", "env": "leak"},
    ]
    log.write_text("\n".join(value if isinstance(value, str) else json.dumps(value) for value in records), encoding="utf-8")
    result = runner.invoke(agent_app, ["logs", "--task-id", wanted, "--lines", "1", "--format", "json"], env=env)
    assert result.exit_code == 0
    lines = json.loads(result.stdout)["data"]["lines"]
    assert lines == [{"event": "provider.event", "task_id": wanted, "session_id": "session-1",
                      "provider_version": "1.15.11", "state": "running"}]
    assert "leak" not in result.stdout


def test_logs_accept_actual_append_shape_when_provider_event_has_no_reason(tmp_path):
    env = _env(tmp_path)
    paths = agent_cmd.load_agent_paths(env, home=tmp_path)
    agent_cmd.append_agent_log(
        paths, "provider.event", task_id="a" * 32, session_id="session-1",
        provider_version="1.15.11", state="running", reason_code="",
    )
    on_disk = json.loads(paths.log_path.read_text(encoding="utf-8"))
    assert "reason_code" not in on_disk
    result = runner.invoke(agent_app, ["logs", "--task-id", "a" * 32, "--format", "json"], env=env)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"]["lines"] == [on_disk]


@pytest.mark.parametrize(("field", "value"), [
    ("task_id", "PRIVATE_PASSWORD"),
    ("session_id", "PRIVATE_PASSWORD"),
    ("provider_version", "PRIVATE_PASSWORD"),
    ("state", "PRIVATE_PASSWORD"),
    ("reason_code", "PRIVATE_PASSWORD"),
])
def test_logs_drop_records_that_smuggle_secrets_through_allowed_fields(tmp_path, field, value):
    env = _env(tmp_path)
    log = tmp_path / "log/agent.log"
    log.parent.mkdir()
    record = {
        "event": "provider.event", "task_id": "a" * 32,
        "session_id": "session-1", "provider_version": "1.15.11", "state": "running",
    }
    record[field] = value
    log.write_text(json.dumps(record), encoding="utf-8")
    result = runner.invoke(agent_app, ["logs", "--format", "json"], env=env)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"]["lines"] == []
    assert "PRIVATE_PASSWORD" not in result.stdout


def test_doctor_reports_complete_truthful_check_set(tmp_path, monkeypatch):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    env = _env(tmp_path)
    initialized = runner.invoke(agent_app, [
        "init", "--workspace", str(workspace),
        "--model-endpoint", "https://model.intranet.example/v1",
        "--model-provider", "internal", "--model", "code-1",
        "--allowed-model-host", "model.intranet.example",
        "--credential-env", "MODEL_KEY", "--format", "json",
    ], env=env)
    assert initialized.exit_code == 0
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(agent_cmd.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(agent_cmd, "opencode_version", lambda argv: "1.15.11\n")
    monkeypatch.setattr(agent_cmd, "detect_opencode_platform", lambda: ("linux", "x86_64", "glibc", "baseline"))
    result = runner.invoke(agent_app, ["doctor", "--format", "json"], env=env)
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert {key: payload[key] for key in ("ok", "code", "message")} == {
        "ok": True, "code": "OK", "message": "local prerequisites available",
    }
    assert [item["name"] for item in payload["data"]["checks"]] == [
        "platform", "opencode", "git", "model-endpoint", "skill-cache", "mcp", "workspace",
    ]
    assert [item["classification"] for item in payload["data"]["checks"]] == [
        "required", "required", "required", "required", "required", "advisory", "required",
    ]
    assert all(item["ok"] for item in payload["data"]["checks"] if item["classification"] == "required")
    mcp = next(item for item in payload["data"]["checks"] if item["name"] == "mcp")
    assert mcp["ok"] is False
    assert "not configured" in mcp["detail"]


@pytest.mark.parametrize("failed_name", [
    "platform", "opencode", "git", "model-endpoint", "skill-cache", "workspace",
])
def test_doctor_required_failure_controls_top_level_envelope(
    tmp_path, monkeypatch, failed_name,
):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    env = _env(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = {
        "allowed_workspaces": [str(workspace)],
        "model_endpoint": "https://model.intranet.example/v1",
        "model_provider": "internal", "model_name": "code-1",
        "allowed_model_hosts": ["model.intranet.example"],
        "credential_env_names": ["MODEL_KEY"],
    }
    if failed_name == "model-endpoint":
        config["model_endpoint"] = None
    if failed_name == "workspace":
        config["allowed_workspaces"] = [str(tmp_path / "missing-workspace")]
    (config_dir / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    if failed_name == "skill-cache":
        cache.rmdir()
    monkeypatch.setattr(
        agent_cmd, "detect_opencode_platform",
        ((lambda: (_ for _ in ()).throw(ValueError("unsupported")))
         if failed_name == "platform" else
         (lambda: ("linux", "x86_64", "glibc", "baseline"))),
    )
    monkeypatch.setattr(
        agent_cmd.shutil, "which",
        lambda name: None if name == failed_name else f"/usr/bin/{name}",
    )
    monkeypatch.setattr(agent_cmd, "opencode_version", lambda argv: "1.15.11\n")

    result = runner.invoke(agent_app, ["doctor", "--format", "json"], env=env)
    payload = json.loads(result.stdout)
    assert result.exit_code == 12
    assert {key: payload[key] for key in ("ok", "code", "message")} == {
        "ok": False, "code": "AGENT_PROVIDER_UNAVAILABLE",
        "message": "required local prerequisites unavailable",
    }
    checks = payload["data"]["checks"]
    failed = next(item for item in checks if item["name"] == failed_name)
    assert failed["classification"] == "required" and failed["ok"] is False
    mcp = next(item for item in checks if item["name"] == "mcp")
    assert mcp["classification"] == "advisory" and mcp["ok"] is False


def test_skillctl_approval_is_truthful_advisory_distribution_check(tmp_path):
    from skillify.install.opencode_distribution import check_opencode_distribution

    payload = b"approved opencode bundle"
    data = load_manifest(Path("infra/offline/opencode-manifest.json"))
    artifact = next(item for item in data["artifacts"] if (
        item["arch"], item["libc"], item["cpu"]
    ) == ("x86_64", "glibc", "baseline"))
    artifact["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "opencode-linux-x64-baseline.tar.gz").write_bytes(payload)
    checks = check_opencode_distribution(
        manifest_path=manifest, artifact_root=artifacts,
        platform_detector=lambda: ("linux", "x86_64", "glibc", "baseline"),
        version_runner=lambda argv: "1.15.11\n",
    )
    assert [check.name for check in checks] == [
        "opencode-manifest", "opencode-platform", "opencode-version",
        "opencode-checksum", "skillctl-approval",
    ]
    approval = checks[-1]
    assert approval.ok is False
    assert approval.classification == "advisory"
    assert "not installable" in approval.detail
    assert all(check.ok for check in checks if check.classification == "required")


def test_runbook_distinguishes_runtime_doctor_from_skillctl_package_approval():
    text = Path("docs/deployment/offline-opencode.md").read_text(encoding="utf-8")
    assert "`skillctl-approval`" in text
    assert "advisory" in text
    assert "does not fail runtime doctor" in text


def test_doctor_fails_closed_on_unsupported_platform_even_with_binaries(tmp_path, monkeypatch):
    _, env = _registered(tmp_path)
    monkeypatch.setattr(agent_cmd.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(agent_cmd, "opencode_version", lambda argv: "1.15.11\n")
    monkeypatch.setattr(
        agent_cmd, "detect_opencode_platform",
        lambda: (_ for _ in ()).throw(ValueError("S1 supports Linux only")),
    )
    result = runner.invoke(agent_app, ["doctor", "--format", "json"], env=env)
    payload = json.loads(result.stdout)
    assert result.exit_code == 12 and payload["code"] == "AGENT_PROVIDER_UNAVAILABLE"
    platform_check = next(item for item in payload["data"]["checks"] if item["name"] == "platform")
    assert platform_check == {
        "name": "platform", "ok": False, "detail": "unsupported platform",
        "classification": "required",
    }


@pytest.mark.parametrize("configured", [
    {"opencode_manifest_path": "/absolute/manifest.json"},
    {"opencode_artifact_root": "/absolute/artifacts"},
    {"opencode_manifest_path": "relative.json", "opencode_artifact_root": "/absolute/artifacts"},
])
def test_doctor_invalid_distribution_config_wins_over_missing_path(tmp_path, monkeypatch, configured):
    env = _env(tmp_path)
    config = tmp_path / "config/config.yaml"
    config.parent.mkdir()
    config.write_text(yaml.safe_dump(configured), encoding="utf-8")
    monkeypatch.setattr(agent_cmd.shutil, "which", lambda name: None)
    result = runner.invoke(agent_app, ["doctor", "--format", "json"], env=env)
    assert result.exit_code == 10
    assert json.loads(result.stdout)["code"] == "AGENT_CONFIG_INVALID"


@pytest.mark.parametrize("version_result", [
    "1.15.10\n",
    subprocess.TimeoutExpired(["/opt/opencode", "--version"], 5),
    subprocess.CalledProcessError(2, ["/opt/opencode", "--version"]),
])
def test_direct_cli_run_cannot_launch_unsupported_binary(tmp_path, monkeypatch, version_result):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    env = _env(tmp_path)
    initialized = runner.invoke(agent_app, [
        "init", "--workspace", str(workspace),
        "--model-endpoint", "https://model.intranet.example/v1",
        "--model-provider", "internal", "--model", "code-1",
        "--allowed-model-host", "model.intranet.example",
        "--credential-env", "MODEL_KEY", "--format", "json",
    ], env=env)
    assert initialized.exit_code == 0
    launched = []
    monkeypatch.setenv("MODEL_KEY", "private")
    monkeypatch.setattr("skillify.agent.providers.opencode.shutil.which", lambda executable: "/opt/opencode")
    def version_runner(argv):
        if isinstance(version_result, BaseException):
            raise version_result
        return version_result
    provider = OpenCodeProvider(
        popen=lambda *args, **kwargs: launched.append(args) or FakeProcess(),
        version_runner=version_runner,
    )
    monkeypatch.setattr(agent_cmd, "_build_provider", lambda: provider)
    result = runner.invoke(agent_app, [
        "run", "--workspace", str(workspace), "--task", "inspect", "--format", "json",
    ], env=env)
    assert result.exit_code == 13
    assert json.loads(result.stdout) == {
        "ok": False, "code": "AGENT_PROVIDER_FAILED",
        "message": "provider execution failed", "data": {},
    }
    assert launched == []


def test_manifest_records_fail_closed_skillctl_supply_chain_metadata():
    path = Path("infra/offline/opencode-manifest.json")
    data = load_manifest(path)
    validate_manifest(data)
    skillctl = data["skillctl"]
    assert set(skillctl) == {
        "version", "platforms", "sha256", "license", "sourceUrl", "intranetUri", "installable",
    }
    assert skillctl["installable"] is False
    placeholder = Path(skillctl["intranetUri"].removeprefix("file://"))
    repository_placeholder = Path("infra/offline") / placeholder.name
    assert hashlib.sha256(repository_placeholder.read_bytes()).hexdigest() == skillctl["sha256"]
    inspected = select_skillctl(data, platform_name="linux-x86_64", require_installable=False)
    assert inspected.version == "0.1.0" and inspected.installable is False
    with pytest.raises(ArtifactNotApproved, match="approval is pending"):
        select_skillctl(data, platform_name="linux-x86_64")
    with pytest.raises(ManifestInvalid, match="does not support"):
        select_skillctl(data, platform_name="linux-riscv64", require_installable=False)


@pytest.mark.parametrize("unsafe", [
    {"share": "auto"},
    {"model": "public/model"},
    {"provider": {"public": {"options": {"apiKey": "secret"}}}},
    {"plugin": ["https://public.example/plugin"]},
])
def test_source_config_rejects_unsafe_or_conflicting_fields(tmp_path, monkeypatch, unsafe):
    source = tmp_path / "user.json"
    source.write_text(json.dumps(unsafe), encoding="utf-8")
    provider, _, _ = _provider(monkeypatch)
    with pytest.raises(OpenCodeError, match="user config"):
        provider.start(_spec(tmp_path, source))


def test_source_config_merges_only_safe_settings_without_mutation(tmp_path, monkeypatch):
    source = tmp_path / "user.json"
    original = json.dumps({"theme": "approved", "keybinds": {"command_palette": "ctrl+p"}}, sort_keys=True)
    source.write_text(original, encoding="utf-8")
    (tmp_path / "generated").mkdir(mode=0o755)
    provider, _, _ = _provider(monkeypatch)
    provider.start(_spec(tmp_path, source))
    generated_path = tmp_path / "generated/opencode.json"
    generated = json.loads(generated_path.read_text(encoding="utf-8"))
    assert generated["theme"] == "approved"
    assert generated["keybinds"] == {"command_palette": "ctrl+p"}
    assert generated["share"] == "disabled" and generated["autoupdate"] is False
    assert source.read_text(encoding="utf-8") == original
    assert source != generated_path
    assert generated_path.stat().st_mode & 0o777 == 0o600
    assert generated_path.parent.stat().st_mode & 0o777 == 0o700


def test_source_config_cannot_alias_generated_config(tmp_path, monkeypatch):
    generated = tmp_path / "generated/opencode.json"
    generated.parent.mkdir()
    generated.write_text(json.dumps({"theme": "approved"}), encoding="utf-8")
    provider, _, _ = _provider(monkeypatch)
    with pytest.raises(OpenCodeError, match="isolated"):
        provider.start(_spec(tmp_path, generated))
    assert json.loads(generated.read_text(encoding="utf-8")) == {"theme": "approved"}


@pytest.mark.parametrize("payload", ["[]", "{", json.dumps({"theme": {"nested": "bad"}})])
def test_source_config_rejects_malformed_or_invalid_shape(tmp_path, monkeypatch, payload):
    source = tmp_path / "user.json"
    source.write_text(payload, encoding="utf-8")
    provider, _, _ = _provider(monkeypatch)
    with pytest.raises(OpenCodeError, match="user config"):
        provider.start(_spec(tmp_path, source))
