"""Standard Skillify zip adapter: safe extraction and Native preview creation."""

from __future__ import annotations

import shutil
from pathlib import Path

from skillify.common.config import SkillifyConfig
from skillify.validator import ValidationIssue, validate_skill_dir
from skillify.web.build_models import BuildRecord
from skillify.web.build_service import store_for_config
from skillify.web.upload import safe_extract_zip
from skillify.webhook.archive import resolve_archive_root


class UploadRejected(Exception):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("uploaded skill failed validation: " + "; ".join(str(issue) for issue in issues))


class NamespaceOwnershipNotConfiguredError(Exception):
    pass


def create_native_zip_build(
    zip_path: Path,
    cfg: SkillifyConfig,
    *,
    uploader: str,
    work_dir: Path,
) -> BuildRecord:
    extracted_dir = work_dir / "extracted"
    safe_extract_zip(
        zip_path,
        extracted_dir,
        max_extracted_bytes=cfg.max_extracted_bytes,
        max_extracted_files=cfg.max_extracted_files,
    )
    skill_root = resolve_archive_root(extracted_dir)
    validation = validate_skill_dir(
        skill_root,
        namespace_aware=False,
        check_directory_name=False,
    )
    if not validation.ok:
        raise UploadRejected(validation.issues)

    store = store_for_config(cfg)
    record = store.create(uploader, "native_zip")
    try:
        shutil.copytree(skill_root, record.workspace, dirs_exist_ok=True)
        return store.load(record.build_id, uploader)
    except Exception:
        store.delete(record.build_id, uploader)
        raise
