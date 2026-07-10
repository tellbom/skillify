"""Core webhook logic: a Forgejo push webhook payload -> validate -> package -> publish (T2.1c)."""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from typing import Any

import yaml

from skillify.common.config import SkillifyConfig
from skillify.common.skill_dir import InvalidDeclaredName, rehome_to_declared_name
from skillify.packaging.pack import PackagingError
from skillify.publish.forgejo_client import ForgejoClient, ForgejoError
from skillify.publish.publisher import AlreadyPublishedError, PublishNotConfiguredError, publish_skill_dir
from skillify.webhook.archive import ArchiveError, fetch_and_extract_archive

# Only react to tag pushes shaped like "refs/tags/vX.Y.Z[-pre][+build]" — a specific
# version to package needs a version, and pack_skill/publish_skill_dir already enforce
# that skill.yaml's own `version` is valid SemVer, so this only needs to be permissive
# enough to extract a candidate version string for the cross-check below.
_TAG_REF_RE = re.compile(r"^refs/tags/v(?P<version>.+)$")

# M-G (docs/review-m2-m6.md): owner/repo_name/tag_version all come straight from the
# webhook's JSON body — used to build a filesystem path (work_dir) below, so a payload
# naming e.g. owner="../../etc" must be rejected before it ever touches a path, not just
# "handled" by uuid-uniqueness (which only fixes the concurrency half of this).
_PATH_SAFE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class WebhookHandlingError(Exception):
    pass


@dataclass
class WebhookResult:
    status: str  # "published" | "ignored" | "error"
    detail: str
    org: str | None = None
    repo: str | None = None
    tag: str | None = None
    release_html_url: str | None = None
    index_error: str | None = None


def _reject_path_unsafe(value: str, field_name: str) -> None:
    if not _PATH_SAFE_RE.match(value) or value in (".", ".."):
        raise WebhookHandlingError(f"webhook payload {field_name} {value!r} is not a safe path segment")


def _extract_repo_identity(payload: dict[str, Any]) -> tuple[str, str]:
    repository = payload.get("repository") or {}
    repo_name = repository.get("name")
    owner = repository.get("owner") or {}
    owner_name = owner.get("username") or owner.get("login") if isinstance(owner, dict) else None
    if not owner_name:
        full_name = repository.get("full_name")  # fallback: "<owner>/<repo>"
        if full_name and "/" in full_name:
            owner_name = full_name.split("/", 1)[0]
    if not repo_name or not owner_name:
        raise WebhookHandlingError(
            "webhook payload missing repository.name / repository.owner.username (or full_name)"
        )
    _reject_path_unsafe(repo_name, "repository.name")
    _reject_path_unsafe(owner_name, "repository.owner")
    return owner_name, repo_name


def handle_push_event(payload: dict[str, Any], cfg: SkillifyConfig) -> WebhookResult:
    """Handle a single Forgejo "push" webhook delivery.

    Non-tag pushes (branch pushes, etc.) are reported as `status="ignored"` rather than an
    error — a webhook is typically configured for the whole repo, and branch pushes aren't
    something to package. Only `refs/tags/v*` pushes attempt a publish.
    """
    ref = payload.get("ref", "")
    match = _TAG_REF_RE.match(ref)
    if not match:
        return WebhookResult(status="ignored", detail=f"not a version-tag push (ref={ref!r})")
    tag_version = match.group("version")
    _reject_path_unsafe(tag_version, "tag version")
    tag = f"v{tag_version}"

    owner, repo_name = _extract_repo_identity(payload)

    if not cfg.forgejo_url or not cfg.forgejo_token:
        raise WebhookHandlingError("forgejo_url/forgejo_token not configured on the webhook service")

    # M-G: a unique-per-delivery work_dir (not just owner__repo__version) so two concurrent
    # redeliveries of the same tag — or a redelivery racing the original — can't `rmtree`
    # each other's in-progress extraction. The old `if work_dir.exists(): rmtree` cleanup
    # this replaced was itself only needed because the path was reused across deliveries.
    work_dir = cfg.cache_dir / "webhook-work" / f"{owner}__{repo_name}__{tag_version}__{uuid.uuid4().hex}"
    work_dir.mkdir(parents=True)

    try:
        client = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
        skill_root = fetch_and_extract_archive(client, owner, repo_name, tag, work_dir)

        manifest_path = skill_root / "skill.yaml"
        if not manifest_path.is_file():
            raise WebhookHandlingError(f"{owner}/{repo_name}@{tag}: no skill.yaml in the pushed tree")
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        # Same spirit as C1 (installer re-verifies manifest identity): the tag names the
        # version being released, so it must agree with what the manifest itself declares —
        # otherwise a stray/mistagged push could silently release the wrong version number.
        if manifest.get("version") != tag_version:
            raise WebhookHandlingError(
                f"{owner}/{repo_name}@{tag}: skill.yaml version {manifest.get('version')!r} "
                f"does not match the pushed tag's version {tag_version!r}"
            )

        # Forgejo/Gitea archive tarballs wrap content in a dir like "<repo>-<sha>/", which
        # `fetch_and_extract_archive` unwraps but doesn't rename — pack_skill/validate_skill_dir
        # require the directory's own basename to equal the manifest's `name` field (spec §4
        # rule 3, standalone case), so re-home the tree under a correctly-named dir first.
        declared_name = manifest.get("name") or repo_name
        try:
            publish_src_dir = rehome_to_declared_name(skill_root, declared_name, work_dir / "publish-src")
        except InvalidDeclaredName as exc:
            raise WebhookHandlingError(f"{owner}/{repo_name}@{tag}: {exc}") from exc

        result = publish_skill_dir(publish_src_dir, cfg, org_override=owner)
    except AlreadyPublishedError as exc:
        return WebhookResult(status="ignored", detail=str(exc), org=exc.org, repo=exc.repo, tag=exc.tag)
    except (PackagingError, PublishNotConfiguredError, ForgejoError, ArchiveError) as exc:
        raise WebhookHandlingError(str(exc)) from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return WebhookResult(
        status="published",
        detail="ok",
        org=result.org,
        repo=result.repo,
        tag=result.tag,
        release_html_url=result.release_html_url,
        index_error=result.index_error,
    )
