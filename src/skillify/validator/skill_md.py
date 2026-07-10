"""Parse and validate SKILL.md's YAML frontmatter (spec §4 rule 5)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from skillify.validator.errors import ValidationResult

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)

REQUIRED_FRONTMATTER_FIELDS = ("name", "description")


def parse_frontmatter(text: str) -> dict[str, Any] | None:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    data = yaml.safe_load(match.group(1))
    return data if isinstance(data, dict) else None


def validate_skill_md(skill_md_path: Path, result: ValidationResult) -> None:
    if not skill_md_path.is_file():
        result.add("SKILL.md", "file not found")
        return
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        result.add("SKILL.md", f"could not read file: {exc}")
        return

    frontmatter = None
    try:
        frontmatter = parse_frontmatter(text)
    except yaml.YAMLError as exc:
        result.add("SKILL.md:frontmatter", f"invalid YAML: {exc}")
        return

    if frontmatter is None:
        result.add("SKILL.md:frontmatter", "missing or malformed '---' YAML frontmatter block")
        return

    for field_name in REQUIRED_FRONTMATTER_FIELDS:
        value = frontmatter.get(field_name)
        if not isinstance(value, str) or not value.strip():
            result.add(f"SKILL.md:frontmatter.{field_name}", "required and must be a non-empty string")
