"""Tests for T1.4a — agent adapter / projection layer."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

from skillify.common.config import SkillifyConfig
from skillify.install.lock import SkillLock, read_lock
from skillify.install.projector import (
    ProjectionError,
    load_agent_rule,
    project_to_targets,
    remove_projections,
    resolve_target_dir,
)


def _symlinks_supported() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        dst = Path(tmp) / "dst"
        src.mkdir()
        try:
            os.symlink(src, dst, target_is_directory=True)
            return True
        except OSError:
            return False


def _make_installed_skill(cfg: SkillifyConfig, namespace: str = "excel", name: str = "pivot-analysis") -> SkillLock:
    skill_dir = cfg.skills_dir / namespace / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: pivot-analysis\ndescription: x\n---\nbody\n", encoding="utf-8")
    (skill_dir / "skill.yaml").write_text("manifestVersion: 1\n", encoding="utf-8")
    lock = SkillLock(
        namespace=namespace, name=name, version="0.1.0", sha256="deadbeef", source="test",
        installedAt="2026-01-01T00:00:00+00:00",
    )
    from skillify.install.lock import write_lock

    write_lock(cfg.locks_dir, lock)
    return lock


def test_default_agent_configs_are_seeded_on_first_use(tmp_path: Path) -> None:
    cfg = SkillifyConfig(home=tmp_path / "home")
    rule = load_agent_rule(cfg, "claude")
    assert rule.agent == "claude"
    assert (cfg.agents_dir / "claude.yaml").is_file()
    assert (cfg.agents_dir / "opencode.yaml").is_file()


def test_reserved_agents_are_rejected(tmp_path: Path) -> None:
    cfg = SkillifyConfig(home=tmp_path / "home")
    with pytest.raises(ProjectionError, match="reserved"):
        load_agent_rule(cfg, "codex")


def test_unknown_agent_is_rejected(tmp_path: Path) -> None:
    cfg = SkillifyConfig(home=tmp_path / "home")
    with pytest.raises(ProjectionError, match="unknown"):
        load_agent_rule(cfg, "bogus-agent")


def test_project_to_claude_target_uses_copy_on_windows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    home = tmp_path / "home"
    cfg = SkillifyConfig(home=home)
    lock = _make_installed_skill(cfg)

    # Redirect claude's target dir under tmp_path instead of the real ~/.claude.
    rule = load_agent_rule(cfg, "claude")
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{(tmp_path / 'claude-home' / 'skills' / '{namespace}__{name}').as_posix()}'\nlinkMode: auto\n",
        encoding="utf-8",
    )

    updated_lock = project_to_targets(cfg, lock, ["claude"])
    target = resolve_target_dir(load_agent_rule(cfg, "claude"), "excel", "pivot-analysis")
    assert target.is_dir()
    assert not target.is_symlink()  # copy mode on win32
    assert (target / "SKILL.md").is_file()
    assert updated_lock.targets == ["claude"]

    stored = read_lock(cfg.locks_dir, "excel", "pivot-analysis")
    assert stored.targets == ["claude"]


def test_project_refuses_to_replace_unowned_existing_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    cfg = SkillifyConfig(home=tmp_path / "home")
    lock = _make_installed_skill(cfg)
    target = tmp_path / "claude-home" / "skills" / "excel__pivot-analysis"
    target.mkdir(parents=True)
    (target / "user.txt").write_text("keep", encoding="utf-8")
    (cfg.agents_dir / "claude.yaml").parent.mkdir(parents=True, exist_ok=True)
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{target.as_posix()}'\nlinkMode: copy\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectionError, match="unowned"):
        project_to_targets(cfg, lock, ["claude"])
    assert (target / "user.txt").read_text(encoding="utf-8") == "keep"


def test_project_refuses_new_template_target_even_when_agent_was_previously_owned(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    cfg = SkillifyConfig(home=tmp_path / "home")
    lock = _make_installed_skill(cfg)
    first = tmp_path / "first" / "excel__pivot-analysis"
    (cfg.agents_dir / "claude.yaml").parent.mkdir(parents=True, exist_ok=True)
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{first.as_posix()}'\nlinkMode: copy\n",
        encoding="utf-8",
    )
    lock = project_to_targets(cfg, lock, ["claude"])

    user_target = tmp_path / "moved" / "excel__pivot-analysis"
    user_target.mkdir(parents=True)
    (user_target / "user.txt").write_text("keep", encoding="utf-8")
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{user_target.as_posix()}'\nlinkMode: copy\n",
        encoding="utf-8",
    )
    with pytest.raises(ProjectionError, match="unowned"):
        project_to_targets(cfg, lock, ["claude"])
    assert (user_target / "user.txt").read_text(encoding="utf-8") == "keep"


def test_project_refuses_file_directory_type_confusion_in_owned_copy(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    cfg = SkillifyConfig(home=tmp_path / "home")
    lock = _make_installed_skill(cfg)
    target = tmp_path / "copy" / "excel__pivot-analysis"
    (cfg.agents_dir / "claude.yaml").parent.mkdir(parents=True, exist_ok=True)
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{target.as_posix()}'\nlinkMode: copy\n",
        encoding="utf-8",
    )
    lock = project_to_targets(cfg, lock, ["claude"])
    (target / "SKILL.md").unlink()
    (target / "SKILL.md").mkdir()
    (target / "SKILL.md/user.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ProjectionError, match="unowned"):
        project_to_targets(cfg, lock, ["claude"])
    assert (target / "SKILL.md/user.txt").read_text(encoding="utf-8") == "keep"


def test_remove_refuses_moved_template_user_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    cfg = SkillifyConfig(home=tmp_path / "home")
    lock = _make_installed_skill(cfg)
    first = tmp_path / "first-remove" / "excel__pivot-analysis"
    (cfg.agents_dir / "claude.yaml").parent.mkdir(parents=True, exist_ok=True)
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{first.as_posix()}'\nlinkMode: copy\n",
        encoding="utf-8",
    )
    lock = project_to_targets(cfg, lock, ["claude"])
    user_target = tmp_path / "remove-moved" / "excel__pivot-analysis"
    user_target.mkdir(parents=True)
    (user_target / "user.txt").write_text("keep", encoding="utf-8")
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{user_target.as_posix()}'\nlinkMode: copy\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectionError, match="unowned"):
        remove_projections(cfg, lock, ["claude"])
    assert (user_target / "user.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.skipif(not _symlinks_supported(), reason="symlinks require elevated privileges on this host")
def test_project_uses_symlink_when_forced(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cfg = SkillifyConfig(home=home)
    lock = _make_installed_skill(cfg)

    (cfg.agents_dir / "claude.yaml").parent.mkdir(parents=True, exist_ok=True)
    from skillify.install.agent_defaults import ensure_default_agent_configs

    ensure_default_agent_configs(cfg.agents_dir)
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{(tmp_path / 'claude-home' / 'skills' / '{namespace}__{name}').as_posix()}'\nlinkMode: symlink\n",
        encoding="utf-8",
    )

    project_to_targets(cfg, lock, ["claude"])
    target = resolve_target_dir(load_agent_rule(cfg, "claude"), "excel", "pivot-analysis")
    assert target.is_symlink()


def test_project_fails_clearly_when_not_installed(tmp_path: Path) -> None:
    cfg = SkillifyConfig(home=tmp_path / "home")
    lock = SkillLock(
        namespace="excel", name="ghost", version="0.1.0", sha256="x", source="test",
        installedAt="2026-01-01T00:00:00+00:00",
    )
    with pytest.raises(ProjectionError, match="not installed"):
        project_to_targets(cfg, lock, ["claude"])


def test_remove_projections_cleans_up_and_updates_lock(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    cfg = SkillifyConfig(home=tmp_path / "home")
    lock = _make_installed_skill(cfg)
    (cfg.agents_dir / "claude.yaml").parent.mkdir(parents=True, exist_ok=True)
    from skillify.install.agent_defaults import ensure_default_agent_configs

    ensure_default_agent_configs(cfg.agents_dir)
    (cfg.agents_dir / "claude.yaml").write_text(
        f"agent: claude\ntargetDirTemplate: '{(tmp_path / 'claude-home' / 'skills' / '{namespace}__{name}').as_posix()}'\nlinkMode: auto\n",
        encoding="utf-8",
    )

    lock = project_to_targets(cfg, lock, ["claude"])
    target = resolve_target_dir(load_agent_rule(cfg, "claude"), "excel", "pivot-analysis")
    assert target.exists()

    lock = remove_projections(cfg, lock, ["claude"])
    assert not target.exists()
    assert lock.targets == []


def test_auto_select_targets_only_picks_present_agents(tmp_path: Path, monkeypatch) -> None:
    import skillify.install.agent_defaults as agent_defaults

    monkeypatch.setattr(
        agent_defaults, "AGENT_PRESENCE_MARKERS", {"claude": tmp_path / "claude-present"}
    )
    (tmp_path / "claude-present").mkdir()

    assert agent_defaults.auto_select_targets(["claude", "opencode"]) == ["claude"]
    assert agent_defaults.auto_select_targets(["opencode"]) == []
    assert agent_defaults.auto_select_targets(["claude", "project"]) == ["claude"]


def test_auto_select_targets_excludes_project() -> None:
    from skillify.install.agent_defaults import auto_select_targets

    # "project" is cwd-relative, never auto-selected regardless of presence markers.
    assert auto_select_targets(["project"]) == []
