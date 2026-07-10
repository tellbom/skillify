"""Shared publish logic: package a skill dir + push it to Forgejo as a Release.

Used by both `skillctl publish` (T1.3, interactive/local) and the webhook packaging
service (T2.1, `push`/tag-triggered/automatic) so the two never drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from skillify.common.config import SkillifyConfig
from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.ingest import ReleaseEvent, upsert_release
from skillify.packaging.pack import PackagingError, PackResult, pack_skill
from skillify.publish.forgejo_client import ForgejoClient, ForgejoError


class PublishNotConfiguredError(Exception):
    pass


class AlreadyPublishedError(Exception):
    """Raised when the resolved org/repo already has a release for this version's tag.

    Versions are immutable once published (PLAN.md §1) — this is not a transient
    failure, it means the manifest's `version` needs to be bumped.
    """

    def __init__(self, org: str, repo: str, tag: str):
        super().__init__(f"{org}/{repo} already has a release for {tag}")
        self.org = org
        self.repo = repo
        self.tag = tag


@dataclass
class PublishResult:
    pack_result: PackResult
    org: str
    repo: str
    tag: str
    release_html_url: str
    index_error: str | None = None  # T2.2: set if best-effort index-write failed


def _author_display(author: Any) -> str:
    if isinstance(author, dict):
        name = author.get("name", "")
        email = author.get("email")
        return f"{name} <{email}>" if email else name
    return str(author)


def _index_release(cfg: SkillifyConfig, result: PackResult, release_html_url: str) -> str | None:
    """Best-effort (T2.2): the Postgres index is a derived cache rebuildable from Forgejo
    (PLAN.md §1), so a missing/unreachable index DB must never fail an actual publish —
    the Release itself is already the source of truth by the time this runs."""
    if not cfg.index_db_url:
        return None
    try:
        engine = make_engine(cfg.index_db_url)
        init_db(engine)
        with session_scope(engine) as session:
            upsert_release(
                session,
                ReleaseEvent(
                    namespace=result.namespace,
                    name=result.name,
                    version=result.version,
                    description=result.description,
                    author=_author_display(result.author),
                    tags=result.tags,
                    checksum=result.sha256,
                    release_url=release_html_url,
                    published_at=datetime.now(timezone.utc),
                    orchestration=result.orchestration,
                ),
            )
        return None
    except Exception as exc:  # noqa: BLE001 - see docstring
        return str(exc)


def publish_skill_dir(
    skill_dir: Path,
    cfg: SkillifyConfig,
    *,
    org_override: str | None = None,
    extra_release_notes: str | None = None,
) -> PublishResult:
    """Validate + package `skill_dir`, then create/upload it as a Forgejo Release.

    `extra_release_notes` (T4.2): appended to the Release body — used by the web upload
    endpoint to record who uploaded it (Keycloak identity) when publishing happens under
    the backend's own Forgejo service-account token rather than a per-user one (see
    TASKS.md M4 for why: no per-user Forgejo OAuth token exchange is implemented).

    Raises `PackagingError` (validation failed), `PublishNotConfiguredError` (no
    forgejo_url/token), `AlreadyPublishedError` (tag already released), or
    `ForgejoError` (any other Forgejo API failure).
    """
    result = pack_skill(skill_dir, cfg.cache_dir / "dist")

    if not cfg.forgejo_url or not cfg.forgejo_token:
        raise PublishNotConfiguredError("forgejo_url / forgejo_token not configured")

    org = org_override or cfg.forgejo_org or result.namespace
    repo = result.name
    tag = f"v{result.version}"
    client = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)

    client.ensure_org_repo(org, repo)

    existing = client.get_release_by_tag(org, repo, tag)
    if existing is not None:
        raise AlreadyPublishedError(org, repo, tag)

    body = f"sha256={result.sha256}"
    if extra_release_notes:
        body = f"{extra_release_notes}\n{body}"
    release = client.create_release(
        org, repo, tag_name=tag, name=f"{result.name} {result.version}", body=body,
    )
    for asset_path in (result.tarball_path, result.checksum_path, result.artifact_manifest_path):
        client.upload_release_asset(org, repo, release.id, asset_path)

    index_error = _index_release(cfg, result, release.html_url)

    return PublishResult(
        pack_result=result, org=org, repo=repo, tag=tag, release_html_url=release.html_url,
        index_error=index_error,
    )
