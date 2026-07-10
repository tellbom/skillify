"""Tests for `skillctl update` — including the F2 fix (update must resolve new
`dependencies.skills` added in a newer version, not just reinstall the root skill)."""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from skillify.cli.main import app
from skillify.cli.publish_cmd import run_publish
from skillify.common.config import SkillifyConfig
from skillify.install.lock import read_lock
from tests.fake_forgejo import fake_forgejo  # noqa: F401

runner = CliRunner()


class _Console:
    def print(self, *a, **k):
        pass


def _write_skill(skill_dir: Path, *, namespace: str, name: str, version: str, skill_deps: list[str] | None = None) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill.\n---\nbody\n", encoding="utf-8"
    )
    deps_yaml = ""
    if skill_deps:
        deps_list = "\n".join(f"    - {d}" for d in skill_deps)
        deps_yaml = f"dependencies:\n  skills:\n{deps_list}\n"
    (skill_dir / "skill.yaml").write_text(
        f"manifestVersion: 1\nnamespace: {namespace}\nname: {name}\nversion: {version}\n"
        f"description: test skill.\nauthor: tester\nlicense: MIT\nruntime: claude-agent-skill\n"
        f"targets: [claude]\n{deps_yaml}",
        encoding="utf-8",
    )


def _publish(tmp_path: Path, fake_forgejo, monkeypatch, skill_dir: Path) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "publish-home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    run_publish(skill_dir=skill_dir, dry_run=False, console=_Console(), err_console=_Console())


def test_update_picks_up_new_version(tmp_path: Path, fake_forgejo, monkeypatch) -> None:
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    home = tmp_path / "install-home"
    monkeypatch.setenv("SKILLIFY_HOME", str(home))

    pivot_dir = tmp_path / "src" / "excel" / "pivot-analysis"
    _write_skill(pivot_dir, namespace="excel", name="pivot-analysis", version="0.1.0")
    _publish(tmp_path, fake_forgejo, monkeypatch, pivot_dir)
    monkeypatch.setenv("SKILLIFY_HOME", str(home))  # _publish() clobbers SKILLIFY_HOME; restore it

    install_result = runner.invoke(app, ["install", "excel/pivot-analysis"])
    assert install_result.exit_code == 0, install_result.output

    shutil.rmtree(pivot_dir)
    _write_skill(pivot_dir, namespace="excel", name="pivot-analysis", version="0.2.0")
    _publish(tmp_path, fake_forgejo, monkeypatch, pivot_dir)
    monkeypatch.setenv("SKILLIFY_HOME", str(home))

    update_result = runner.invoke(app, ["update", "excel/pivot-analysis"])
    assert update_result.exit_code == 0, update_result.output
    assert "0.1.0 -> 0.2.0" in update_result.output

    cfg = SkillifyConfig(home=home)
    stored = read_lock(cfg.locks_dir, "excel", "pivot-analysis")
    assert stored.version == "0.2.0"


def test_update_resolves_newly_added_skill_dependency(tmp_path: Path, fake_forgejo, monkeypatch) -> None:
    """F2: a version bump that adds dependencies.skills must pull the new dep on update."""
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    home = tmp_path / "install-home"
    monkeypatch.setenv("SKILLIFY_HOME", str(home))

    # v1.0.0 of the dependency, published up front so it's resolvable later.
    lookup_dir = tmp_path / "src" / "excel" / "lookup"
    _write_skill(lookup_dir, namespace="excel", name="lookup", version="1.0.0")
    _publish(tmp_path, fake_forgejo, monkeypatch, lookup_dir)

    # pivot-analysis v0.1.0 has NO skill dependency yet.
    pivot_dir = tmp_path / "src" / "excel" / "pivot-analysis"
    _write_skill(pivot_dir, namespace="excel", name="pivot-analysis", version="0.1.0")
    _publish(tmp_path, fake_forgejo, monkeypatch, pivot_dir)
    monkeypatch.setenv("SKILLIFY_HOME", str(home))  # _publish() clobbers SKILLIFY_HOME; restore it

    install_result = runner.invoke(app, ["install", "excel/pivot-analysis"])
    assert install_result.exit_code == 0, install_result.output

    cfg = SkillifyConfig(home=home)
    assert not (cfg.skills_dir / "excel" / "lookup").exists()  # not pulled in yet

    # v0.2.0 adds a dependency on excel/lookup.
    shutil.rmtree(pivot_dir)
    _write_skill(
        pivot_dir, namespace="excel", name="pivot-analysis", version="0.2.0",
        skill_deps=["excel/lookup@^1.0.0"],
    )
    _publish(tmp_path, fake_forgejo, monkeypatch, pivot_dir)
    monkeypatch.setenv("SKILLIFY_HOME", str(home))

    update_result = runner.invoke(app, ["update", "excel/pivot-analysis"])
    assert update_result.exit_code == 0, update_result.output
    assert "Installed dependency excel/lookup@1.0.0" in update_result.output

    assert (cfg.skills_dir / "excel" / "lookup" / "SKILL.md").is_file()
    stored = read_lock(cfg.locks_dir, "excel", "pivot-analysis")
    assert stored.skillDeps == ["excel/lookup@^1.0.0"]
