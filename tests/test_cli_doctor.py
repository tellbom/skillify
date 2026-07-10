"""Tests for T1.1b — `skillctl doctor`."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from skillify.cli.doctor_cmd import run_doctor
from skillify.common.config import SkillifyConfig


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
