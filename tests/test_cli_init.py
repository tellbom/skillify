"""Tests for T1.1a — `skillctl init`."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from skillify.cli.main import app
from skillify.validator import validate_skill_dir

runner = CliRunner()


@pytest.mark.parametrize("template", ["prompt", "python"])
def test_init_generates_valid_skill(tmp_path: Path, template: str) -> None:
    result = runner.invoke(app, ["init", "excel/pivot-analysis", "--template", template, "--dest", str(tmp_path)])
    assert result.exit_code == 0, result.output

    skill_dir = tmp_path / "excel" / "pivot-analysis"
    assert skill_dir.is_dir()
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "skill.yaml").is_file()
    assert (skill_dir / "README.md").is_file()

    validation = validate_skill_dir(skill_dir, namespace_aware=True)
    assert validation.ok, [str(i) for i in validation.issues]

    if template == "python":
        assert (skill_dir / "requirements.txt").is_file()
        assert (skill_dir / "scripts" / "run.py").is_file()


def test_init_rejects_bad_identifier(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "not-namespaced", "--dest", str(tmp_path)])
    assert result.exit_code == 2


def test_init_rejects_existing_dir(tmp_path: Path) -> None:
    (tmp_path / "excel" / "pivot-analysis").mkdir(parents=True)
    result = runner.invoke(app, ["init", "excel/pivot-analysis", "--dest", str(tmp_path)])
    assert result.exit_code == 1


def test_init_rejects_bad_template(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "excel/pivot-analysis", "--template", "bogus", "--dest", str(tmp_path)])
    assert result.exit_code == 2
