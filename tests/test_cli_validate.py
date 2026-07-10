"""CLI-level smoke tests for `skillctl validate`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from skillify.cli.main import app
from tests.fixtures import VALID_MANIFEST, VALID_SKILL_MD

runner = CliRunner()


def test_cli_validate_ok(tmp_path: Path) -> None:
    skill_dir = tmp_path / "pivot-analysis"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")
    (skill_dir / "skill.yaml").write_text(VALID_MANIFEST, encoding="utf-8")

    result = runner.invoke(app, ["validate", str(skill_dir)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_cli_validate_fail(tmp_path: Path) -> None:
    skill_dir = tmp_path / "pivot-analysis"
    skill_dir.mkdir()

    result = runner.invoke(app, ["validate", str(skill_dir)])
    assert result.exit_code == 1
