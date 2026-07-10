"""Tests for T1.5 — recursive skill-to-skill dependency resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillify.cli.publish_cmd import run_publish
from skillify.common.config import SkillifyConfig
from skillify.install.dependencies import DependencyError, install_with_dependencies
from skillify.install.lock import read_lock
from tests.fake_forgejo import fake_forgejo  # noqa: F401


class _Console:
    def print(self, *a, **k):
        pass


def _write_skill(skill_dir: Path, *, namespace: str, name: str, version: str, skill_deps: list[str] | None = None) -> None:
    skill_dir.mkdir(parents=True)
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


def test_install_resolves_skill_dependency(tmp_path: Path, fake_forgejo, monkeypatch) -> None:
    lookup_dir = tmp_path / "src" / "excel" / "lookup"
    _write_skill(lookup_dir, namespace="excel", name="lookup", version="1.0.0")
    _publish(tmp_path, fake_forgejo, monkeypatch, lookup_dir)

    pivot_dir = tmp_path / "src" / "excel" / "pivot-analysis"
    _write_skill(
        pivot_dir, namespace="excel", name="pivot-analysis", version="0.1.0",
        skill_deps=["excel/lookup@^1.0.0"],
    )
    _publish(tmp_path, fake_forgejo, monkeypatch, pivot_dir)

    cfg = SkillifyConfig(
        forgejo_url=f"http://127.0.0.1:{fake_forgejo.server_port}", forgejo_token="tok",
        home=tmp_path / "install-home",
    )
    installed = install_with_dependencies("excel/pivot-analysis", cfg=cfg)

    assert set(installed) == {"excel/pivot-analysis", "excel/lookup"}
    assert installed["excel/lookup"].version == "1.0.0"
    assert (cfg.skills_dir / "excel" / "lookup" / "SKILL.md").is_file()
    assert (cfg.skills_dir / "excel" / "pivot-analysis" / "SKILL.md").is_file()

    stored = read_lock(cfg.locks_dir, "excel", "pivot-analysis")
    assert stored.skillDeps == ["excel/lookup@^1.0.0"]


def test_install_picks_highest_satisfying_version(tmp_path: Path, fake_forgejo, monkeypatch) -> None:
    lookup_dir = tmp_path / "src" / "excel" / "lookup"
    for version in ("1.0.0", "1.5.0", "2.0.0"):
        _write_skill(lookup_dir, namespace="excel", name="lookup", version=version)
        _publish(tmp_path, fake_forgejo, monkeypatch, lookup_dir)
        import shutil

        shutil.rmtree(lookup_dir)

    pivot_dir = tmp_path / "src" / "excel" / "pivot-analysis"
    _write_skill(
        pivot_dir, namespace="excel", name="pivot-analysis", version="0.1.0",
        skill_deps=["excel/lookup@^1.0.0"],
    )
    _publish(tmp_path, fake_forgejo, monkeypatch, pivot_dir)

    cfg = SkillifyConfig(
        forgejo_url=f"http://127.0.0.1:{fake_forgejo.server_port}", forgejo_token="tok",
        home=tmp_path / "install-home",
    )
    installed = install_with_dependencies("excel/pivot-analysis", cfg=cfg)
    # ^1.0.0 excludes 2.0.0 -> highest matching is 1.5.0
    assert installed["excel/lookup"].version == "1.5.0"


def test_dependency_cycle_is_detected(tmp_path: Path, fake_forgejo, monkeypatch) -> None:
    a_dir = tmp_path / "src" / "ns" / "a"
    _write_skill(a_dir, namespace="ns", name="a", version="1.0.0", skill_deps=["ns/b@^1.0.0"])
    _publish(tmp_path, fake_forgejo, monkeypatch, a_dir)

    b_dir = tmp_path / "src" / "ns" / "b"
    _write_skill(b_dir, namespace="ns", name="b", version="1.0.0", skill_deps=["ns/a@^1.0.0"])
    _publish(tmp_path, fake_forgejo, monkeypatch, b_dir)

    cfg = SkillifyConfig(
        forgejo_url=f"http://127.0.0.1:{fake_forgejo.server_port}", forgejo_token="tok",
        home=tmp_path / "install-home",
    )
    with pytest.raises(DependencyError, match="cycle"):
        install_with_dependencies("ns/a", cfg=cfg)


def test_no_satisfying_version_raises(tmp_path: Path, fake_forgejo, monkeypatch) -> None:
    lookup_dir = tmp_path / "src" / "excel" / "lookup"
    _write_skill(lookup_dir, namespace="excel", name="lookup", version="1.0.0")
    _publish(tmp_path, fake_forgejo, monkeypatch, lookup_dir)

    pivot_dir = tmp_path / "src" / "excel" / "pivot-analysis"
    _write_skill(
        pivot_dir, namespace="excel", name="pivot-analysis", version="0.1.0",
        skill_deps=["excel/lookup@^9.0.0"],
    )
    _publish(tmp_path, fake_forgejo, monkeypatch, pivot_dir)

    cfg = SkillifyConfig(
        forgejo_url=f"http://127.0.0.1:{fake_forgejo.server_port}", forgejo_token="tok",
        home=tmp_path / "install-home",
    )
    with pytest.raises(DependencyError, match="no published version"):
        install_with_dependencies("excel/pivot-analysis", cfg=cfg)


def test_diamond_dependency_installs_shared_dep_once(tmp_path: Path, fake_forgejo, monkeypatch) -> None:
    """F4: A->B, A->C, B->D, C->D must install D exactly once, not twice."""
    d_dir = tmp_path / "src" / "ns" / "d"
    _write_skill(d_dir, namespace="ns", name="d", version="1.0.0")
    _publish(tmp_path, fake_forgejo, monkeypatch, d_dir)

    b_dir = tmp_path / "src" / "ns" / "b"
    _write_skill(b_dir, namespace="ns", name="b", version="1.0.0", skill_deps=["ns/d@^1.0.0"])
    _publish(tmp_path, fake_forgejo, monkeypatch, b_dir)

    c_dir = tmp_path / "src" / "ns" / "c"
    _write_skill(c_dir, namespace="ns", name="c", version="1.0.0", skill_deps=["ns/d@^1.0.0"])
    _publish(tmp_path, fake_forgejo, monkeypatch, c_dir)

    a_dir = tmp_path / "src" / "ns" / "a"
    _write_skill(
        a_dir, namespace="ns", name="a", version="1.0.0",
        skill_deps=["ns/b@^1.0.0", "ns/c@^1.0.0"],
    )
    _publish(tmp_path, fake_forgejo, monkeypatch, a_dir)

    cfg = SkillifyConfig(
        forgejo_url=f"http://127.0.0.1:{fake_forgejo.server_port}", forgejo_token="tok",
        home=tmp_path / "install-home",
    )

    import skillify.install.dependencies as deps_module

    call_log: list[str] = []
    real_install_skill = deps_module.install_skill

    def _counting_install_skill(identifier, **kwargs):
        call_log.append(identifier.split("@", 1)[0])
        return real_install_skill(identifier, **kwargs)

    monkeypatch.setattr(deps_module, "install_skill", _counting_install_skill)

    installed = install_with_dependencies("ns/a", cfg=cfg)

    assert set(installed) == {"ns/a", "ns/b", "ns/c", "ns/d"}
    assert call_log.count("ns/d") == 1, f"expected ns/d installed exactly once, got calls: {call_log}"


def test_conflicting_versions_of_same_dependency_raises(tmp_path: Path, fake_forgejo, monkeypatch) -> None:
    d_dir = tmp_path / "src" / "ns" / "d"
    for version in ("1.0.0", "2.0.0"):
        _write_skill(d_dir, namespace="ns", name="d", version=version)
        _publish(tmp_path, fake_forgejo, monkeypatch, d_dir)
        import shutil

        shutil.rmtree(d_dir)

    b_dir = tmp_path / "src" / "ns" / "b"
    _write_skill(b_dir, namespace="ns", name="b", version="1.0.0", skill_deps=["ns/d@^1.0.0"])
    _publish(tmp_path, fake_forgejo, monkeypatch, b_dir)

    c_dir = tmp_path / "src" / "ns" / "c"
    _write_skill(c_dir, namespace="ns", name="c", version="1.0.0", skill_deps=["ns/d@^2.0.0"])
    _publish(tmp_path, fake_forgejo, monkeypatch, c_dir)

    a_dir = tmp_path / "src" / "ns" / "a"
    _write_skill(
        a_dir, namespace="ns", name="a", version="1.0.0",
        skill_deps=["ns/b@^1.0.0", "ns/c@^1.0.0"],
    )
    _publish(tmp_path, fake_forgejo, monkeypatch, a_dir)

    cfg = SkillifyConfig(
        forgejo_url=f"http://127.0.0.1:{fake_forgejo.server_port}", forgejo_token="tok",
        home=tmp_path / "install-home",
    )
    with pytest.raises(DependencyError, match="version conflict"):
        install_with_dependencies("ns/a", cfg=cfg)
