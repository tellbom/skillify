"""Agent adapter layer: project the neutral install dir into per-agent target
dirs via symlink (posix) or copy (Windows), per `~/.skillify/agents/<agent>.yaml` (T1.4a).
"""

from __future__ import annotations

import os
import filecmp
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from skillify.common.config import SkillifyConfig
from skillify.install.agent_defaults import (
    KNOWN_AGENTS,
    RESERVED_UNIMPLEMENTED_AGENTS,
    agent_rule_path,
    ensure_default_agent_configs,
)
from skillify.install.lock import SkillLock, write_lock


class ProjectionError(Exception):
    pass


@dataclass
class AgentRule:
    agent: str
    target_dir_template: str
    link_mode: str  # "auto" | "symlink" | "copy"


def load_agent_rule(cfg: SkillifyConfig, agent: str) -> AgentRule:
    if agent not in KNOWN_AGENTS:
        raise ProjectionError(f"unknown agent target {agent!r} (known: {sorted(KNOWN_AGENTS)})")
    if agent in RESERVED_UNIMPLEMENTED_AGENTS:
        raise ProjectionError(f"agent target {agent!r} is reserved but not yet adapted (PLAN.md §2)")

    ensure_default_agent_configs(cfg.agents_dir)
    path = agent_rule_path(cfg.agents_dir, agent)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AgentRule(
        agent=data["agent"], target_dir_template=data["targetDirTemplate"], link_mode=data.get("linkMode", "auto")
    )


def resolve_target_dir(rule: AgentRule, namespace: str, name: str) -> Path:
    expanded = rule.target_dir_template.format(namespace=namespace, name=name)
    # Keep the configured leaf path itself. ``resolve()`` follows an existing
    # projection symlink and can turn a repeat install into a mutation of the
    # neutral source directory.
    return Path(expanded).expanduser().absolute()


def agent_skills_root(rule: AgentRule) -> Path:
    """The agent's skills-root directory (parent of any per-skill projection),
    e.g. `~/.claude/skills` for template `~/.claude/skills/{namespace}__{name}`.
    Used by `doctor` (F1) to check presence without needing a specific skill."""
    prefix = rule.target_dir_template.split("{", 1)[0].rstrip("/\\")
    return Path(prefix).expanduser().resolve()


def _effective_link_mode(rule: AgentRule) -> str:
    if rule.link_mode in ("symlink", "copy"):
        return rule.link_mode
    return "copy" if sys.platform == "win32" else "symlink"


def _matches_owned_projection(target: Path, source: Path) -> bool:
    """Return true only when an existing projection still matches its source."""
    if target.is_symlink():
        try:
            return target.resolve(strict=True) == source.resolve(strict=True)
        except OSError:
            return False
    if not target.is_dir() or source.is_symlink() or not source.is_dir():
        return False
    try:
        target_names = sorted(item.name for item in os.scandir(target))
        source_names = sorted(item.name for item in os.scandir(source))
    except OSError:
        return False
    if target_names != source_names:
        return False
    for name in source_names:
        source_item = source / name
        target_item = target / name
        try:
            source_mode = os.lstat(source_item).st_mode
            target_mode = os.lstat(target_item).st_mode
        except OSError:
            return False
        if stat.S_IFMT(source_mode) != stat.S_IFMT(target_mode):
            return False
        if stat.S_ISDIR(source_mode):
            if not _matches_owned_projection(target_item, source_item):
                return False
        elif stat.S_ISREG(source_mode):
            if not filecmp.cmp(source_item, target_item, shallow=False):
                return False
        elif stat.S_ISLNK(source_mode):
            try:
                if os.readlink(source_item) != os.readlink(target_item):
                    return False
            except OSError:
                return False
        else:
            return False
    return True


def _project_one(cfg: SkillifyConfig, lock: SkillLock, agent: str) -> Path:
    rule = load_agent_rule(cfg, agent)
    source_dir = cfg.skills_dir / lock.namespace / lock.name
    if not source_dir.is_dir():
        raise ProjectionError(f"{lock.identifier} is not installed in the neutral dir ({source_dir})")

    target_dir = resolve_target_dir(rule, lock.namespace, lock.name)
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    mode = _effective_link_mode(rule)
    if target_dir.is_symlink() or target_dir.exists():
        matching = _matches_owned_projection(target_dir, source_dir)
        representation_matches = (
            (mode == "symlink" and target_dir.is_symlink())
            or (mode == "copy" and target_dir.is_dir() and not target_dir.is_symlink())
        )
        if agent not in lock.targets or not matching or not representation_matches:
            raise ProjectionError(f"refusing to replace unowned projection target ({target_dir})")
        return target_dir

    if mode == "symlink":
        os.symlink(source_dir, target_dir, target_is_directory=True)
    else:
        shutil.copytree(source_dir, target_dir)
    return target_dir


def project_to_targets(cfg: SkillifyConfig, lock: SkillLock, targets: list[str]) -> SkillLock:
    for agent in targets:
        _project_one(cfg, lock, agent)
    lock.targets = sorted(set(lock.targets) | set(targets))
    write_lock(cfg.locks_dir, lock)
    return lock


def _remove_one(cfg: SkillifyConfig, lock: SkillLock, agent: str) -> None:
    rule = load_agent_rule(cfg, agent)
    target_dir = resolve_target_dir(rule, lock.namespace, lock.name)
    source_dir = cfg.skills_dir / lock.namespace / lock.name
    if not target_dir.is_symlink() and not target_dir.exists():
        return
    if agent not in lock.targets or not _matches_owned_projection(target_dir, source_dir):
        raise ProjectionError(f"refusing to remove unowned projection target ({target_dir})")
    if target_dir.is_symlink() or target_dir.is_file():
        target_dir.unlink(missing_ok=True)
    elif target_dir.is_dir():
        shutil.rmtree(target_dir)


def remove_projections(cfg: SkillifyConfig, lock: SkillLock, targets: list[str]) -> SkillLock:
    for agent in targets:
        _remove_one(cfg, lock, agent)
    lock.targets = sorted(set(lock.targets) - set(targets))
    write_lock(cfg.locks_dir, lock)
    return lock
