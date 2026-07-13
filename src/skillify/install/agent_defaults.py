"""Default agent-adapter rules seeded into ~/.skillify/agents/*.yaml on first use (T1.4a).

These are best-effort defaults for each target's skills-directory convention:
- claude: `~/.claude/skills/<dir>/SKILL.md` matches Anthropic's published Agent Skills layout.
- opencode: `~/.config/opencode/skills/<dir>/SKILL.md` is OpenCode's documented global
  Agent Skills location.
- project: PLAN.md §2 names "project=项目本地 .skills" — relative to the current working
  directory the projection command is run from.

Every rule is user-editable after first generation; this module only supplies the seed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_RULES: dict[str, dict] = {
    "claude": {
        "agent": "claude",
        "targetDirTemplate": "~/.claude/skills/{namespace}__{name}",
        "linkMode": "auto",  # auto -> symlink on posix, copy on Windows (PLAN.md §4)
    },
    "opencode": {
        "agent": "opencode",
        # OpenCode requires the containing directory to exactly match SKILL.md's
        # frontmatter name, so the namespace cannot be encoded in this path.
        "targetDirTemplate": "~/.config/opencode/skills/{name}",
        "linkMode": "auto",
    },
    "project": {
        "agent": "project",
        "targetDirTemplate": "./.skills/{namespace}__{name}",
        "linkMode": "auto",
    },
}

KNOWN_AGENTS = set(DEFAULT_RULES) | {"codex", "aider"}
RESERVED_UNIMPLEMENTED_AGENTS = {"codex", "aider"}  # PLAN.md §2: "预留 codex/aider"

# Marker dirs used to decide whether an agent is "already installed on this machine"
# (PLAN.md §4: install with no --target projects to "manifest 声明且本机已装的 agent").
# "project" is excluded — it's a per-project convention (cwd-relative), not a
# machine-wide agent install, so it's never auto-selected; it must be requested explicitly.
AGENT_PRESENCE_MARKERS: dict[str, Path] = {
    "claude": Path.home() / ".claude",
    "opencode": Path.home() / ".config" / "opencode",
}


def agent_rule_path(agents_dir: Path, agent: str) -> Path:
    return agents_dir / f"{agent}.yaml"


def ensure_default_agent_configs(agents_dir: Path) -> None:
    agents_dir.mkdir(parents=True, exist_ok=True)
    for agent, rule in DEFAULT_RULES.items():
        path = agent_rule_path(agents_dir, agent)
        if not path.is_file():
            path.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")


def auto_select_targets(declared_targets: list[str]) -> list[str]:
    """Manifest-declared targets that are also detected as installed on this machine."""
    return [
        t for t in declared_targets
        if t in AGENT_PRESENCE_MARKERS and AGENT_PRESENCE_MARKERS[t].is_dir()
    ]
