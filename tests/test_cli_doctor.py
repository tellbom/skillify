"""Tests for T1.1b — `skillctl doctor`."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from skillify.cli.doctor_cmd import run_doctor
from skillify.common.config import (
    AgentLocalConfig, SkillifyConfig, load_agent_paths,
)


class _FakeForgejoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib override)
        if self.path == "/api/v1/version":
            self._reply(200, b'{"version":"10.0.0"}')
        elif self.path == "/api/v1/user":
            if self.headers.get("Authorization") == "token good-token":
                self._reply(200, b'{"login":"tester"}')
            else:
                self._reply(401, b"{}")
        else:
            self._reply(200, b"ok")

    def _reply(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - silence test server logs
        pass


@pytest.fixture()
def fake_server():
    server = HTTPServer(("127.0.0.1", 0), _FakeForgejoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=2)


class _NullConsole:
    def print(self, *args, **kwargs) -> None:
        pass


def test_doctor_all_pass_against_fake_services(tmp_path: Path, fake_server: str) -> None:
    cfg = SkillifyConfig(
        forgejo_url=fake_server,
        forgejo_token="good-token",
        devpi_index_url=fake_server,
        home=tmp_path / "home",
    )
    # Point every configured agent's skills-root at a dir that exists, so the whole
    # run is green end-to-end without touching the real ~/.claude / ~/.opencode.
    from skillify.install.agent_defaults import ensure_default_agent_configs

    cfg.ensure_dirs()
    ensure_default_agent_configs(cfg.agents_dir)
    for agent in ("claude", "opencode"):
        root = tmp_path / f"{agent}-root"
        root.mkdir()
        (cfg.agents_dir / f"{agent}.yaml").write_text(
            f"agent: {agent}\ntargetDirTemplate: '{(root / '{namespace}__{name}').as_posix()}'\nlinkMode: auto\n",
            encoding="utf-8",
        )

    ok = run_doctor(console=_NullConsole(), config=cfg)

    assert ok is True


def test_doctor_dynamically_picks_up_configured_agents(tmp_path: Path, fake_server: str) -> None:
    """F1: doctor must not hardcode {claude, codex} — it reads ~/.skillify/agents/*.yaml,
    checks claude/opencode (both present by default), and never checks reserved/unimplemented
    agents like codex even if a codex.yaml were added."""
    cfg = SkillifyConfig(
        forgejo_url=fake_server, forgejo_token="good-token", devpi_index_url=fake_server,
        home=tmp_path / "home",
    )
    from skillify.install.agent_defaults import ensure_default_agent_configs

    cfg.ensure_dirs()
    ensure_default_agent_configs(cfg.agents_dir)
    assert (cfg.agents_dir / "opencode.yaml").is_file()

    seen: list[str] = []

    class _RecordingConsole:
        def print(self, *args, **kwargs) -> None:
            if args:
                seen.append(str(args[0]))

    run_doctor(console=_RecordingConsole(), config=cfg)
    joined = "\n".join(seen)
    assert "agent-dir:claude" in joined
    assert "agent-dir:opencode" in joined
    assert "agent-dir:codex" not in joined
    assert "agent-dir:project" not in joined


def test_doctor_fails_on_bad_token(tmp_path: Path, fake_server: str) -> None:
    cfg = SkillifyConfig(
        forgejo_url=fake_server,
        forgejo_token="wrong-token",
        devpi_index_url=fake_server,
        home=tmp_path / "home",
    )
    ok = run_doctor(console=_NullConsole(), config=cfg)
    assert ok is False


def test_doctor_fails_when_forgejo_unconfigured(tmp_path: Path) -> None:
    cfg = SkillifyConfig(home=tmp_path / "home")
    ok = run_doctor(console=_NullConsole(), config=cfg)
    assert ok is False


def test_doctor_fails_when_forgejo_unreachable(tmp_path: Path) -> None:
    cfg = SkillifyConfig(
        forgejo_url="http://127.0.0.1:1",  # nothing listens on port 1
        home=tmp_path / "home",
    )
    ok = run_doctor(console=_NullConsole(), config=cfg)
    assert ok is False


def _isolated_green_config(tmp_path: Path, fake_server: str) -> SkillifyConfig:
    from skillify.install.agent_defaults import ensure_default_agent_configs
    cfg = SkillifyConfig(
        forgejo_url=fake_server, forgejo_token="good-token",
        devpi_index_url=fake_server, home=tmp_path / "skillify-home",
    )
    cfg.ensure_dirs(); ensure_default_agent_configs(cfg.agents_dir)
    for agent in ("claude", "opencode"):
        root = tmp_path / f"{agent}-doctor-root"; root.mkdir()
        (cfg.agents_dir / f"{agent}.yaml").write_text(
            f"agent: {agent}\ntargetDirTemplate: '{(root / '{namespace}__{name}').as_posix()}'\nlinkMode: auto\n",
            encoding="utf-8",
        )
    return cfg


def test_doctor_unconfigured_distribution_preserves_green_baseline_without_user_home(
    tmp_path: Path, fake_server: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _isolated_green_config(tmp_path, fake_server)
    paths = load_agent_paths({}, home=tmp_path / "isolated-agent-home")
    monkeypatch.setattr(Path, "home", classmethod(
        lambda cls: (_ for _ in ()).throw(AssertionError("real user home must not be read"))
    ))
    def unexpected_platform():
        raise AssertionError("unconfigured distribution must be skipped")
    ok = run_doctor(
        console=_NullConsole(), config=cfg, agent_paths=paths,
        agent_config=AgentLocalConfig(), platform_detector=unexpected_platform,
        version_runner=lambda argv: (_ for _ in ()).throw(AssertionError("version must not run")),
    )
    assert ok is True


def test_doctor_configured_temporary_distribution_is_green(
    tmp_path: Path, fake_server: str,
) -> None:
    cfg = _isolated_green_config(tmp_path, fake_server)
    payload = b"approved opencode bundle"
    digest = hashlib.sha256(payload).hexdigest()
    manifest_data = {
        "schemaVersion": 1, "opencodeVersion": "1.15.11", "skillctlVersion": "0.1.0",
        "skillctl": {
            "version": "0.1.0", "platforms": ["linux-x86_64"], "sha256": "a" * 64,
            "license": "MIT", "sourceUrl": "https://github.com/tellbom/skillify/archive/refs/tags/v0.1.0.tar.gz",
            "intranetUri": "file:///opt/skillify/offline/skillctl/0.1.0/skillctl-0.1.0-approval-placeholder.json",
            "installable": False,
        },
        "artifacts": [{
            "version": "1.15.11", "skillctlVersion": "0.1.0", "os": "linux",
            "arch": "x86_64", "libc": "glibc", "cpu": "avx2", "sha256": digest,
            "license": "MIT",
            "sourceUrl": "https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-x64.tar.gz",
            "intranetUri": "file:///opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64.tar.gz",
        }],
    }
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    artifacts = tmp_path / "artifacts"; artifacts.mkdir()
    (artifacts / "opencode-linux-x64.tar.gz").write_bytes(payload)
    paths = load_agent_paths({}, home=tmp_path / "isolated-agent-home")
    agent_config = AgentLocalConfig(
        opencode_manifest_path=str(manifest), opencode_artifact_root=str(artifacts),
    )
    seen: list[str] = []
    class RecordingConsole:
        def print(self, *args, **kwargs):
            if args: seen.append(str(args[0]))
    ok = run_doctor(
        console=RecordingConsole(), config=cfg, agent_paths=paths, agent_config=agent_config,
        platform_detector=lambda: ("linux", "x86_64", "glibc", "avx2"),
        version_runner=lambda argv: "1.15.11\n",
    )
    assert ok is True
    output = "\n".join(seen)
    assert all(name in output for name in (
        "opencode-manifest", "opencode-platform", "opencode-version", "opencode-checksum",
    ))
