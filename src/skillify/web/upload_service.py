"""Upload orchestration: browser-uploaded zip -> validate -> publish (T4.2)."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from skillify.common.config import SkillifyConfig
from skillify.common.skill_dir import InvalidDeclaredName, rehome_to_declared_name
from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.ownership import NamespaceOwnershipError, claim_or_verify_namespace
from skillify.publish.publisher import PublishResult, publish_skill_dir
from skillify.publish.git_source import push_skill_source
from skillify.validator import ValidationIssue, validate_skill_dir
from skillify.web.upload import safe_extract_zip
from skillify.webhook.archive import resolve_archive_root


class UploadRejected(Exception):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("uploaded skill failed validation: " + "; ".join(str(i) for i in issues))


class NamespaceOwnershipNotConfiguredError(Exception):
    """M-C: raised instead of silently skipping the ownership check when index_db_url isn't
    configured — unlike the index write in publisher.py, this check is a security boundary
    and must fail closed, not best-effort."""


def handle_upload(zip_path: Path, cfg: SkillifyConfig, *, uploader: str, work_dir: Path) -> PublishResult:
    """Extract, validate, and publish an uploaded skill package. Always cleans up `work_dir`.

    Raises `UploadRejected` (bad package, .issues has the structured reasons),
    `skillify.web.upload.UnsafeUpload` (path traversal / symlink in the zip),
    `NamespaceOwnershipError` (M-C: namespace already claimed by another uploader),
    `NamespaceOwnershipNotConfiguredError` (M-C: no index_db_url to check ownership against),
    or whatever `publish_skill_dir` itself raises (PackagingError should be unreachable
    here since validation already ran, but is not swallowed if it somehow occurs).
    """
    try:
        extracted_dir = work_dir / "extracted"
        safe_extract_zip(
            zip_path,
            extracted_dir,
            max_extracted_bytes=cfg.max_extracted_bytes,
            max_extracted_files=cfg.max_extracted_files,
        )
        skill_root = resolve_archive_root(extracted_dir)

        manifest_path = skill_root / "skill.yaml"
        if not manifest_path.is_file():
            raise UploadRejected([ValidationIssue(path="skill.yaml", message="file not found in uploaded package")])
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        declared_name = manifest.get("name")
        if not declared_name:
            raise UploadRejected([ValidationIssue(path="skill.yaml:name", message="required and must be a non-empty string")])
        namespace = manifest.get("namespace")
        if not namespace:
            raise UploadRejected([ValidationIssue(path="skill.yaml:namespace", message="required and must be a non-empty string")])

        try:
            publish_src_dir = rehome_to_declared_name(skill_root, declared_name, work_dir / "publish-src")
        except InvalidDeclaredName as exc:
            raise UploadRejected([ValidationIssue(path="skill.yaml:name", message=str(exc))]) from exc

        validation = validate_skill_dir(publish_src_dir, namespace_aware=False)
        if not validation.ok:
            raise UploadRejected(validation.issues)

        if not cfg.index_db_url:
            raise NamespaceOwnershipNotConfiguredError("index_db_url not configured on this service")
        engine = make_engine(cfg.index_db_url)
        init_db(engine)
        with session_scope(engine) as session:
            claim_or_verify_namespace(
                session, namespace=namespace, username=uploader, claimed_at=datetime.now(timezone.utc)
            )

        if cfg.web_upload_git_enabled:
            push_skill_source(
                publish_src_dir,
                cfg,
                org=cfg.forgejo_org or namespace,
                repo=declared_name,
                tag=f"v{manifest['version']}",
                uploader=uploader,
            )

        return publish_skill_dir(
            publish_src_dir, cfg, extra_release_notes=f"Uploaded via Skillify Web by {uploader}."
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
