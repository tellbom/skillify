"""Agent adapter layer: project the neutral install dir into per-agent target
dirs via symlink (posix) or copy (Windows), per `~/.skillify/agents/<agent>.yaml` (T1.4a).
"""

from __future__ import annotations

import os
import shutil
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
    return Path(expanded).expanduser().resolve()


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


def _project_one(cfg: SkillifyConfig, lock: SkillLock, agent: str) -> Path:
    rule = load_agent_rule(cfg, agent)
    source_dir = cfg.skills_dir / lock.namespace / lock.name
    if not source_dir.is_dir():
        raise ProjectionError(f"{lock.identifier} is not installed in the neutral dir ({source_dir})")

    target_dir = resolve_target_dir(rule, lock.namespace, lock.name)
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    if target_dir.is_symlink() or target_dir.exists():
        if target_dir.is_symlink() or target_dir.is_file():
            target_dir.unlink()
        else:
            shutil.rmtree(target_dir)

    mode = _effective_link_mode(rule)
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
