"""Directory-level validation rules that span multiple files (spec §4 rule 6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skillify.validator.errors import ValidationResult


def validate_directory_layout(
    skill_dir: Path, manifest: dict[str, Any], result: ValidationResult
) -> None:
    python_deps = ((manifest.get("dependencies") or {}).get("python")) or []
    if python_deps:
        has_requirements = (skill_dir / "requirements.txt").is_file()
        has_pyproject = (skill_dir / "pyproject.toml").is_file()
        if not (has_requirements or has_pyproject):
            result.add(
                "directory:requirements.txt",
                "dependencies.python is non-empty but neither requirements.txt "
                "nor pyproject.toml exists at the skill root",
            )
