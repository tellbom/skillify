"""Tests for T1.3 — `skillctl publish` CLI wiring against the fake Forgejo."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from skillify.cli.main import app
from tests.fake_forgejo import fake_forgejo  # noqa: F401
from tests.fixtures import VALID_MANIFEST, VALID_SKILL_MD

runner = CliRunner()


def _make_skill(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "excel" / "pivot-analysis"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")
    (skill_dir / "skill.yaml").write_text(VALID_MANIFEST, encoding="utf-8")
    return skill_dir


def test_publish_dry_run_does_not_need_forgejo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    skill_dir = _make_skill(tmp_path)

    result = runner.invoke(app, ["publish", str(skill_dir), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Packaged" in result.output


def test_publish_rejects_invalid_skill(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    skill_dir = tmp_path / "excel" / "broken"
    skill_dir.mkdir(parents=True)

    result = runner.invoke(app, ["publish", str(skill_dir), "--dry-run"])
    assert result.exit_code == 1


def test_publish_without_config_fails_clearly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SKILLIFY_FORGEJO_URL", raising=False)
    monkeypatch.delenv("SKILLIFY_FORGEJO_TOKEN", raising=False)
    skill_dir = _make_skill(tmp_path)

    result = runner.invoke(app, ["publish", str(skill_dir)])
    assert result.exit_code == 1
    assert "not configured" in result.output


def test_publish_end_to_end_against_fake_forgejo(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    skill_dir = _make_skill(tmp_path)

    result = runner.invoke(app, ["publish", str(skill_dir)])
    assert result.exit_code == 0, result.output
    assert "Published" in result.output
    assert "excel/pivot-analysis@v0.1.0" in result.output

    # Re-publishing the same version must be rejected (immutable artifacts, PLAN §1).
    result2 = runner.invoke(app, ["publish", str(skill_dir)])
    assert result2.exit_code == 1
    assert "already has a release" in result2.output
