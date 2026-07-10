"""Top-level entrypoint: validate a skill directory end-to-end (T0.2)."""

from __future__ import annotations

from pathlib import Path

from skillify.validator.directory import validate_directory_layout
from skillify.validator.errors import ValidationResult
from skillify.validator.manifest import (
    load_manifest_yaml,
    validate_manifest_schema,
    validate_manifest_semantics,
)
from skillify.validator.skill_md import validate_skill_md


def validate_skill_dir(skill_dir: str | Path, *, namespace_aware: bool = False) -> ValidationResult:
    """Validate a single skill directory against the v1 standard format.

    If `namespace_aware`, `skill_dir` is expected to be `<root>/<namespace>/<name>`
    and namespace/name in skill.yaml are checked against those two path segments
    (spec §4 rule 3, namespace-aware case). Otherwise only `name` is checked
    against the directory's own basename (standalone case).
    """
    skill_dir = Path(skill_dir)
    result = ValidationResult()

    if not skill_dir.is_dir():
        result.add(str(skill_dir), "not a directory")
        return result

    if namespace_aware:
        expected_name = skill_dir.name
        expected_namespace = skill_dir.parent.name
    else:
        expected_name = skill_dir.name
        expected_namespace = None

    validate_skill_md(skill_dir / "SKILL.md", result)

    manifest = load_manifest_yaml(skill_dir / "skill.yaml", result)
    if manifest is not None:
        validate_manifest_schema(manifest, result)
        # Only run semantic/dir checks if the manifest at least parsed as a dict;
        # schema errors on individual fields are still reported independently above.
        validate_manifest_semantics(
            manifest,
            result,
            expected_namespace=expected_namespace,
            expected_name=expected_name,
        )
        validate_directory_layout(skill_dir, manifest, result)

    return result
