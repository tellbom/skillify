"""Rebuild Skillify's derived business index from authoritative Forgejo releases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from skillify.common.config import SkillifyConfig
from skillify.index.db import init_db, make_engine, session_scope
from skillify.index.ingest import ReleaseEvent, upsert_release
from skillify.index.governance import derive_artifact_governance
from skillify.publish.forgejo_client import ForgejoClient, ForgejoError, Release


class IndexRebuildError(Exception):
    pass


@dataclass
class RebuildSummary:
    repositories: int = 0
    indexed: int = 0
    skipped: int = 0
    failed: int = 0


def _author_display(author: Any) -> str:
    if isinstance(author, dict):
        name = str(author.get("name", ""))
        email = author.get("email")
        return f"{name} <{email}>" if email else name
    return str(author or "")


def _published_at(release: Release) -> datetime:
    if release.published_at:
        try:
            return datetime.fromisoformat(release.published_at.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _artifact_asset(release: Release):
    return next((asset for asset in release.assets if asset.name.endswith(".artifact.json")), None)


def rebuild_repository(
    cfg: SkillifyConfig,
    owner: str,
    repo: str,
    *,
    client: ForgejoClient | None = None,
) -> RebuildSummary:
    if not cfg.forgejo_url or not cfg.forgejo_token:
        raise IndexRebuildError("forgejo_url / forgejo_token not configured")
    if not cfg.index_db_url:
        raise IndexRebuildError("index_db_url not configured")

    forgejo = client or ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    summary = RebuildSummary(repositories=1)
    engine = make_engine(cfg.index_db_url)
    init_db(engine)

    for release in forgejo.list_releases(owner, repo):
        if release.draft:
            summary.skipped += 1
            continue
        asset = _artifact_asset(release)
        if asset is None:
            summary.skipped += 1
            continue
        try:
            artifact = json.loads(forgejo.fetch_text(asset.browser_download_url))
            manifest = artifact["skillManifest"]
            with session_scope(engine) as session:
                upsert_release(
                    session,
                    ReleaseEvent(
                        namespace=artifact["namespace"],
                        name=artifact["name"],
                        version=artifact["version"],
                        description=manifest.get("description", ""),
                        author=_author_display(manifest.get("author", "")),
                        tags=manifest.get("tags") or [],
                        checksum=artifact["sha256"],
                        release_url=release.html_url,
                        published_at=_published_at(release),
                        orchestration=manifest.get("orchestration") or {},
                        governance=derive_artifact_governance(artifact),
                    ),
                )
            summary.indexed += 1
        except (ForgejoError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            summary.failed += 1
    return summary


def rebuild_all(cfg: SkillifyConfig) -> RebuildSummary:
    if not cfg.forgejo_url or not cfg.forgejo_token:
        raise IndexRebuildError("forgejo_url / forgejo_token not configured")
    client = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    total = RebuildSummary()
    for repository in client.list_repositories():
        result = rebuild_repository(cfg, repository.owner, repository.name, client=client)
        total.repositories += result.repositories
        total.indexed += result.indexed
        total.skipped += result.skipped
        total.failed += result.failed
    return total
