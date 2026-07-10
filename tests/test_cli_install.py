"""CLI-level tests for T1.4 — install/list/remove."""

from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from skillify.cli.main import app
from skillify.packaging.pack import pack_skill
from tests.fixtures import VALID_MANIFEST, VALID_SKILL_MD

runner = CliRunner()


def _make_skill(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "src" / "excel" / "pivot-analysis"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")
    (skill_dir / "skill.yaml").write_text(VALID_MANIFEST, encoding="utf-8")
    return skill_dir


@pytest.fixture()
def static_file_server(tmp_path: Path):
    directory = tmp_path / "static"
    directory.mkdir()
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(directory), **kw)
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, directory
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_install_list_remove_cycle(tmp_path: Path, monkeypatch, static_file_server) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    server, static_dir = static_file_server
    skill_dir = _make_skill(tmp_path)
    result = pack_skill(skill_dir, static_dir)
    url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"

    install_result = runner.invoke(app, ["install", "excel/pivot-analysis@0.1.0", "--source", url])
    assert install_result.exit_code == 0, install_result.output
    assert "Installed" in install_result.output

    list_result = runner.invoke(app, ["list"])
    assert list_result.exit_code == 0
    assert "excel/pivot-analysis@0.1.0" in list_result.output

    remove_result = runner.invoke(app, ["remove", "excel/pivot-analysis"])
    assert remove_result.exit_code == 0
    assert "Removed" in remove_result.output

    list_after = runner.invoke(app, ["list"])
    assert "excel/pivot-analysis" not in list_after.output


def test_list_when_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No skills installed" in result.output


def test_remove_when_not_installed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    result = runner.invoke(app, ["remove", "excel/pivot-analysis"])
    assert result.exit_code == 1


def test_install_with_target_projects_and_remove_cleans_up(
    tmp_path: Path, monkeypatch, static_file_server
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SKILLIFY_HOME", str(home))
    monkeypatch.setattr("sys.platform", "win32")  # force copy mode, avoids symlink privilege issues

    server, static_dir = static_file_server
    skill_dir = _make_skill(tmp_path)
    result = pack_skill(skill_dir, static_dir)
    url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"

    # Redirect claude's projection target under tmp_path instead of the real ~/.claude.
    from skillify.common.config import load_config
    from skillify.install.agent_defaults import ensure_default_agent_configs

    cfg = load_config(home=home)
    ensure_default_agent_configs(cfg.agents_dir)
    claude_target = tmp_path / "claude-home" / "skills" / "{namespace}__{name}"
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{claude_target.as_posix()}'\nlinkMode: auto\n",
        encoding="utf-8",
    )

    install_result = runner.invoke(
        app, ["install", "excel/pivot-analysis@0.1.0", "--source", url, "--target", "claude"]
    )
    assert install_result.exit_code == 0, install_result.output
    assert "projected to: claude" in install_result.output

    projected_dir = tmp_path / "claude-home" / "skills" / "excel__pivot-analysis"
    assert (projected_dir / "SKILL.md").is_file()

    remove_result = runner.invoke(app, ["remove", "excel/pivot-analysis"])
    assert remove_result.exit_code == 0
    assert not projected_dir.exists()


def test_install_without_target_auto_selects_present_agents(
    tmp_path: Path, monkeypatch, static_file_server
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SKILLIFY_HOME", str(home))
    monkeypatch.setattr("sys.platform", "win32")

    server, static_dir = static_file_server
    skill_dir = _make_skill(tmp_path)  # VALID_MANIFEST declares targets: [claude]
    result = pack_skill(skill_dir, static_dir)
    url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"

    from skillify.common.config import load_config
    from skillify.install.agent_defaults import ensure_default_agent_configs
    import skillify.install.agent_defaults as agent_defaults

    cfg = load_config(home=home)
    ensure_default_agent_configs(cfg.agents_dir)
    claude_target = tmp_path / "claude-home" / "skills" / "{namespace}__{name}"
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{claude_target.as_posix()}'\nlinkMode: auto\n",
        encoding="utf-8",
    )
    # Simulate "claude is installed on this machine" without touching the real ~/.claude.
    fake_claude_home = tmp_path / "fake-claude-marker"
    fake_claude_home.mkdir()
    monkeypatch.setattr(agent_defaults, "AGENT_PRESENCE_MARKERS", {"claude": fake_claude_home})

    install_result = runner.invoke(app, ["install", "excel/pivot-analysis@0.1.0", "--source", url])
    assert install_result.exit_code == 0, install_result.output
    assert "auto-selected: claude" in install_result.output
    assert "projected to: claude" in install_result.output

    projected_dir = tmp_path / "claude-home" / "skills" / "excel__pivot-analysis"
    assert (projected_dir / "SKILL.md").is_file()


def test_install_reports_event_when_reporting_enabled(tmp_path: Path, monkeypatch, static_file_server) -> None:
    """T6.2: `skillctl install` best-effort reports an install event, but only when
    both web_base_url and reporting_enabled are explicitly configured (opt-in)."""
    import json
    import threading as _threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _CapturingHandler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self.server.captured.append(json.loads(self.rfile.read(length)))
            self.send_response(204)
            self.end_headers()

    events_server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    events_server.captured = []
    thread = _threading.Thread(target=events_server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("SKILLIFY_WEB_BASE_URL", f"http://127.0.0.1:{events_server.server_port}")
        monkeypatch.setenv("SKILLIFY_REPORTING_ENABLED", "true")

        server, static_dir = static_file_server
        skill_dir = _make_skill(tmp_path)
        result = pack_skill(skill_dir, static_dir)
        url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"

        install_result = runner.invoke(app, ["install", "excel/pivot-analysis@0.1.0", "--source", url])
        assert install_result.exit_code == 0, install_result.output

        assert len(events_server.captured) == 1
        payload = events_server.captured[0]
        assert payload["eventType"] == "install"
        assert payload["version"] == "0.1.0"
    finally:
        events_server.shutdown()
        thread.join(timeout=2)


def test_install_does_not_report_when_disabled(tmp_path: Path, monkeypatch, static_file_server) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SKILLIFY_WEB_BASE_URL", raising=False)
    monkeypatch.delenv("SKILLIFY_REPORTING_ENABLED", raising=False)

    server, static_dir = static_file_server
    skill_dir = _make_skill(tmp_path)
    result = pack_skill(skill_dir, static_dir)
    url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"

    install_result = runner.invoke(app, ["install", "excel/pivot-analysis@0.1.0", "--source", url])
    assert install_result.exit_code == 0, install_result.output
