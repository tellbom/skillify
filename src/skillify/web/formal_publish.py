"""The sole canonical Native workspace -> Skillify publication path."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from skillify.common.config import SkillifyConfig
from skillify.common.skill_dir import InvalidDeclaredName, rehome_to_declared_name
from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.ownership import claim_or_verify_namespace
from skillify.index.publish_jobs import record_job_result
from skillify.publish.git_source import push_skill_source
from skillify.publish.publisher import PublishResult, publish_skill_dir
from skillify.validator import ValidationIssue, validate_skill_dir
from skillify.web.build_models import BuildNotReady, BuildRecord, BuildRevisionConflict
from skillify.web.build_preview import build_preview
from skillify.web.build_service import store_for_config
from skillify.web.upload_service import NamespaceOwnershipNotConfiguredError, UploadRejected


def publish_workspace(
    skill_root: Path,
    cfg: SkillifyConfig,
    *,
    uploader: str,
    work_dir: Path,
) -> PublishResult:
    """Validate and publish one canonical Native workspace through the sole formal path."""
    manifest_path = skill_root / "skill.yaml"
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise UploadRejected([ValidationIssue(path="skill.yaml", message=str(exc))]) from exc
    if not isinstance(manifest, dict):
        raise UploadRejected([ValidationIssue(path="skill.yaml", message="top-level document must be a mapping")])
    declared_name = manifest.get("name")
    namespace = manifest.get("namespace")
    if not isinstance(declared_name, str) or not declared_name:
        raise UploadRejected([ValidationIssue(path="skill.yaml:name", message="required")])
    if not isinstance(namespace, str) or not namespace:
        raise UploadRejected([ValidationIssue(path="skill.yaml:namespace", message="required")])

    copied = work_dir / "source"
    shutil.copytree(skill_root, copied)
    try:
        publish_src = rehome_to_declared_name(copied, declared_name, work_dir / "publish-src")
    except InvalidDeclaredName as exc:
        raise UploadRejected([ValidationIssue(path="skill.yaml:name", message=str(exc))]) from exc
    validation = validate_skill_dir(publish_src, namespace_aware=False)
    if not validation.ok:
        raise UploadRejected(validation.issues)

    version = str(manifest.get("version") or "")
    if not cfg.index_db_url:
        raise NamespaceOwnershipNotConfiguredError("index_db_url not configured on this service")

    try:
        engine = make_engine(cfg.index_db_url)
        init_db(engine)
        with session_scope(engine) as session:
            claim_or_verify_namespace(
                session,
                namespace=namespace,
                username=uploader,
                claimed_at=datetime.now(timezone.utc),
            )

        if cfg.web_upload_git_enabled:
            push_skill_source(
                publish_src,
                cfg,
                org=cfg.forgejo_org or namespace,
                repo=declared_name,
                tag=f"v{manifest['version']}",
                uploader=uploader,
            )

        result = publish_skill_dir(
            publish_src,
            cfg,
            extra_release_notes=f"Published via Skillify Web by {uploader}.",
        )
    except Exception as exc:
        _record_job_best_effort(
            cfg,
            namespace=namespace,
            name=declared_name,
            version=version,
            initiator=uploader,
            status="failed",
            error_message=str(exc),
        )
        raise

    _record_job_best_effort(
        cfg,
        namespace=namespace,
        name=declared_name,
        version=result.pack_result.version,
        initiator=uploader,
        status="succeeded",
        error_message=None,
    )
    return result


def publish_build(
    cfg: SkillifyConfig,
    *,
    owner: str,
    build_id: str,
    expected_revision: int,
) -> tuple[PublishResult, BuildRecord]:
    store = store_for_config(cfg)
    with store.read_lease(build_id, owner) as record:
        if record.revision != expected_revision:
            raise BuildRevisionConflict(record.revision)
        preview = build_preview(record)
    if not preview["publishable"]:
        raise BuildNotReady(
            missing_fields=preview["missingFields"],
            unconfirmed_fields=preview["unconfirmedFields"],
            issues=preview["issues"],
        )
    store.transition_status(
        build_id,
        owner,
        expected_revision,
        allowed={"needs_input", "ready"},
        status="publishing",
    )
    work_dir = cfg.cache_dir / "formal-publish" / build_id
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=False)
    try:
        result = publish_workspace(record.workspace, cfg, uploader=owner, work_dir=work_dir)
    except Exception:
        store.transition_status(
            build_id,
            owner,
            expected_revision,
            allowed={"publishing"},
            status="needs_input",
        )
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    published = store.transition_status(
        build_id,
        owner,
        expected_revision,
        allowed={"publishing"},
        status="published",
    )
    return result, published


def _record_job_best_effort(
    cfg: SkillifyConfig,
    *,
    namespace: str,
    name: str,
    version: str,
    initiator: str,
    status: str,
    error_message: str | None,
) -> None:
    if not cfg.index_db_url:
        return
    try:
        engine = make_engine(cfg.index_db_url)
        init_db(engine)
        with session_scope(engine) as session:
            record_job_result(
                session,
                namespace=namespace,
                name=name,
                version=version,
                initiator=initiator,
                status=status,
                error_message=error_message,
                at=datetime.now(timezone.utc),
            )
    except Exception:
        pass
