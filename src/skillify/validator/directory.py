"""Directory-level validation rules that span multiple files (spec §4 rule 6)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import os
import stat
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

    entrypoints = manifest.get("entrypoints") or {}
    if not isinstance(entrypoints, dict):
        return
    root = skill_dir.absolute()
    for kind, entries in entrypoints.items():
        if not isinstance(entries, dict):
            continue
        for name, value in entries.items():
            issue_path = f"skill.yaml:entrypoints.{kind}.{name}"
            if not isinstance(value, str):
                continue
            pure = PurePosixPath(value)
            if pure.as_posix() != value:
                result.add(issue_path, "referenced path must be a normalized relative file")
                continue
            candidate = root / value
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                result.add(issue_path, "referenced path escapes the artifact root")
                continue
            if not relative.parts or any(part in {"", ".", ".."} for part in pure.parts):
                result.add(issue_path, "referenced path must be a normalized relative file")
                continue
            current = root
            unsafe = False
            for part in relative.parts:
                current = current / part
                try:
                    metadata = os.stat(current, follow_symlinks=False)
                except FileNotFoundError:
                    result.add(issue_path, "referenced file does not exist")
                    unsafe = True
                    break
                except OSError as exc:
                    result.add(issue_path, f"referenced file is unsafe: {exc}")
                    unsafe = True
                    break
                if stat.S_ISLNK(metadata.st_mode):
                    result.add(issue_path, "referenced path must not contain a symlink")
                    unsafe = True
                    break
            if not unsafe and not stat.S_ISREG(metadata.st_mode):
                result.add(issue_path, "referenced path must be a regular file")
