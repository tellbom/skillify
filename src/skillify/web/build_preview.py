"""Canonical preview generation for every Skill build source."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from skillify.validator import validate_skill_dir
from skillify.web.build_models import (
    EXTERNAL_CONFIRMATION_FIELDS,
    REQUIRED_MANIFEST_FIELDS,
    BuildRecord,
)


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _manifest(workspace: Path) -> tuple[dict[str, Any], str]:
    path = workspace / "skill.yaml"
    if not path.is_file():
        return {}, ""
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError):
        return {}, path.read_text(encoding="utf-8", errors="replace")
    return (data if isinstance(data, dict) else {}), text


def _tree(workspace: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not workspace.is_dir():
        return items
    for path in sorted(workspace.rglob("*"), key=lambda item: item.relative_to(workspace).as_posix()):
        relative = path.relative_to(workspace).as_posix()
        if path.is_dir():
            items.append({"path": relative, "type": "directory", "size": None})
        elif path.is_file():
            items.append({"path": relative, "type": "file", "size": path.stat().st_size})
    return items


def build_preview(record: BuildRecord) -> dict[str, Any]:
    manifest, manifest_yaml = _manifest(record.workspace)
    missing = [field for field in REQUIRED_MANIFEST_FIELDS if not _present(manifest.get(field))]
    unconfirmed: list[str] = []
    if record.source_type == "external":
        missing = [
            field
            for field in EXTERNAL_CONFIRMATION_FIELDS
            if not _present(manifest.get(field)) and field not in record.confirmed_fields
        ]
        unconfirmed = sorted(
            field
            for field in EXTERNAL_CONFIRMATION_FIELDS
            if _present(manifest.get(field)) and field not in record.confirmed_fields
        )

    validation = validate_skill_dir(
        record.workspace,
        namespace_aware=False,
        check_directory_name=False,
    )
    issues = [{"path": issue.path, "message": issue.message} for issue in validation.issues]
    publishable = validation.ok and not missing and not unconfirmed
    status = record.status
    if status not in ("publishing", "published"):
        status = "ready" if publishable else "needs_input"

    skill_md_path = record.workspace / "SKILL.md"
    skill_md = skill_md_path.read_text(encoding="utf-8") if skill_md_path.is_file() else ""
    return {
        "buildId": record.build_id,
        "sourceType": record.source_type,
        "revision": record.revision,
        "status": status,
        "expiresAt": record.expires_at,
        "manifest": manifest,
        "manifestYaml": manifest_yaml,
        "skillMd": skill_md,
        "tree": _tree(record.workspace),
        "detectedFacts": record.detected_facts,
        "missingFields": sorted(missing),
        "unconfirmedFields": unconfirmed,
        "issues": issues,
        "publishable": publishable,
    }
