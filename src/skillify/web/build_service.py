"""Source-neutral mutations plus the guided Skill build adapter."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from skillify.common.config import SkillifyConfig
from skillify.web.build_models import BuildRecord, InvalidBuildFile
from skillify.web.build_store import BuildStore

_RESERVED_BUILD_PATHS = {"skill.yaml", "skill.md"}
_STRUCTURAL_DEFAULTS: dict[str, Any] = {
    "manifestVersion": 1,
    "entrypoints": {},
    "orchestration": {},
    "reporting": {"enabled": False},
}
_GUIDED_DEFAULTS: dict[str, Any] = {
    **_STRUCTURAL_DEFAULTS,
    "dependencies": {"python": [], "system": [], "skills": []},
    "permissions": [],
    "tags": [],
}


def store_for_config(cfg: SkillifyConfig) -> BuildStore:
    cfg.ensure_dirs()
    return BuildStore(cfg.cache_dir, ttl_seconds=cfg.build_ttl_seconds)


def _manifest_with_defaults(manifest: dict[str, Any], *, guided: bool) -> dict[str, Any]:
    defaults = _GUIDED_DEFAULTS if guided else _STRUCTURAL_DEFAULTS
    result = {key: value.copy() if isinstance(value, dict) else list(value) if isinstance(value, list) else value
              for key, value in defaults.items()}
    result.update(manifest)
    return result


def _write_manifest(workspace: Path, manifest: dict[str, Any]) -> None:
    (workspace / "skill.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def create_guided_build(
    cfg: SkillifyConfig,
    *,
    owner: str,
    manifest: dict[str, Any],
    skill_md: str,
) -> BuildRecord:
    store = store_for_config(cfg)
    record = store.create("" + owner, "guided", confirmed_fields=set(manifest))
    _write_manifest(record.workspace, _manifest_with_defaults(manifest, guided=True))
    (record.workspace / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return store.load(record.build_id, owner)


def get_build(cfg: SkillifyConfig, *, owner: str, build_id: str) -> BuildRecord:
    return store_for_config(cfg).load(build_id, owner)


def update_build(
    cfg: SkillifyConfig,
    *,
    owner: str,
    build_id: str,
    expected_revision: int,
    manifest: dict[str, Any] | None,
    skill_md: str | None,
) -> BuildRecord:
    store = store_for_config(cfg)
    current = store.load(build_id, owner)

    def mutation(workspace: Path, metadata: dict[str, Any]) -> None:
        if manifest is not None:
            existing: dict[str, Any] = {}
            path = workspace / "skill.yaml"
            if path.is_file():
                loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            existing.update(manifest)
            _write_manifest(
                workspace,
                _manifest_with_defaults(existing, guided=current.source_type == "guided"),
            )
            if current.source_type == "external":
                confirmed = set(metadata.get("confirmedFields") or [])
                confirmed.update(manifest)
                metadata["confirmedFields"] = sorted(confirmed)
        if skill_md is not None:
            (workspace / "SKILL.md").write_text(skill_md, encoding="utf-8")

    return store.mutate(build_id, owner, expected_revision, mutation)


def normalize_build_path(value: str) -> PurePosixPath:
    if not value or "\\" in value or ":" in value:
        raise InvalidBuildFile("file path must be a safe relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise InvalidBuildFile("file path must be a safe relative POSIX path")
    if len(path.parts) == 1 and path.name.casefold() in _RESERVED_BUILD_PATHS:
        raise InvalidBuildFile("skill.yaml and SKILL.md must be changed through the build update API")
    return path


def _workspace_usage(workspace: Path) -> tuple[int, int]:
    files = [path for path in workspace.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def put_build_file(
    cfg: SkillifyConfig,
    *,
    owner: str,
    build_id: str,
    expected_revision: int,
    path: str,
    content: bytes,
) -> BuildRecord:
    relative = normalize_build_path(path)
    store = store_for_config(cfg)

    def mutation(workspace: Path, _metadata: dict[str, Any]) -> None:
        target = workspace.joinpath(*relative.parts)
        current_size = target.stat().st_size if target.is_file() else 0
        file_count, total_size = _workspace_usage(workspace)
        projected_count = file_count if target.is_file() else file_count + 1
        projected_size = total_size - current_size + len(content)
        if projected_count > cfg.max_extracted_files:
            raise InvalidBuildFile(f"build exceeds the {cfg.max_extracted_files} file limit")
        if projected_size > cfg.max_extracted_bytes:
            raise InvalidBuildFile(f"build exceeds the {cfg.max_extracted_bytes} byte limit")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    return store.mutate(build_id, owner, expected_revision, mutation)


def delete_build_file(
    cfg: SkillifyConfig,
    *,
    owner: str,
    build_id: str,
    expected_revision: int,
    path: str,
) -> BuildRecord:
    relative = normalize_build_path(path)
    store = store_for_config(cfg)

    def mutation(workspace: Path, _metadata: dict[str, Any]) -> None:
        target = workspace.joinpath(*relative.parts)
        if not target.is_file():
            raise InvalidBuildFile(f"build file not found: {relative.as_posix()}")
        target.unlink()
        parent = target.parent
        while parent != workspace and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    return store.mutate(build_id, owner, expected_revision, mutation)
