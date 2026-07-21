"""Aggregation logic: Postgres index (T2.2) + Forgejo (README/SKILL.md, release assets) (T3.1)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from skillify.common.config import SkillifyConfig
from skillify.index.events import install_counts
from skillify.index.models import SkillIndexEntry
from skillify.index.queries import get_versions, search
from skillify.index.ratings import rating_stats
from skillify.index.star import has_starred, star_counts
from skillify.index.subscriptions import is_subscribed
from skillify.publish.forgejo_client import ForgejoClient, ForgejoError
from skillify.web.schemas import SkillDetail, SkillSummary, VersionDiff, VersionInfo


def install_command(namespace: str, name: str) -> str:
    return f"skillctl install {namespace}/{name}"


def agent_prompt(namespace: str, name: str, cfg: SkillifyConfig | None = None) -> str:
    """T6.1 — a self-contained, copy-pasteable recipe an agent can follow even without
    `skillctl` available: query the documented detail endpoint for the exact tarball +
    checksum URLs (same artifact `skillctl install` would fetch, C2-precise naming), verify,
    extract. See docs/agent-self-pull.md for the full protocol + security posture (this
    channel is intranet-only per PLAN.md §4/§5; token-gating it is reserved future work —
    T6.1 is explicitly a "预留接口" milestone item, not a hardened production path yet).
    """
    detail_url = f"{(cfg.web_base_url if cfg else None) or '<SKILLIFY_WEB_BASE_URL>'}/api/skills/{namespace}/{name}"
    return (
        f"Install the Skillify skill '{namespace}/{name}' on this machine. Preferred: run "
        f"`skillctl install {namespace}/{name}` if `skillctl` is available and configured. "
        f"Otherwise, self-install: 1) GET {detail_url} and read its `tarballUrl`/`checksumUrl` "
        f"fields; 2) download both; 3) verify the tarball's sha256 matches the checksum file; "
        f"4) extract the tarball into your skills directory (e.g. `~/.claude/skills/"
        f"{namespace}__{name}/` for Claude Code) — do not run anything from the archive before "
        f"verifying the checksum. This endpoint is intranet-only (see docs/agent-self-pull.md)."
    )


def summaries_from_entries(session: Session, entries: list[SkillIndexEntry]) -> list[SkillSummary]:
    """Enrich a page of index entries with community metrics using three batch queries.

    Keeping this aggregation here avoids an N+1 detail request/query pattern on catalog,
    search, and personal-workspace listing pages.
    """
    installs = install_counts(session)
    ratings = rating_stats(session)
    stars = star_counts(session)
    return [_summary_from_entry(entry, installs=installs, ratings=ratings, stars=stars) for entry in entries]


def _summary_from_entry(
    entry: SkillIndexEntry,
    *,
    installs: dict[tuple[str, str], int],
    ratings: dict[tuple[str, str], tuple[float, int]],
    stars: dict[tuple[str, str], int],
) -> SkillSummary:
    key = (entry.namespace, entry.name)
    rating_average, rating_count = ratings.get(key, (None, 0))
    return SkillSummary(
        namespace=entry.namespace,
        name=entry.name,
        version=entry.version,
        description=entry.description,
        author=entry.author,
        tags=entry.tags,
        publishedAt=entry.published_at,
        installCount=installs.get(key, 0),
        ratingAverage=rating_average,
        ratingCount=rating_count,
        starCount=stars.get(key, 0),
    )


def list_skills(
    session: Session,
    query: str | None = None,
    *,
    namespace: str | None = None,
    author: str | None = None,
    tags: list[str] | None = None,
    sort: str = "updated",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SkillSummary], int]:
    """C-4: thin passthrough to `queries.search` — always goes through `search` now (not just
    when `query` is set) so namespace/author/tags/sort/pagination apply uniformly whether or
    not there's a text query. `list_latest` alone no longer has a caller here; it stays in
    `queries.py` for `leaderboard`/`my_skills`/`subscriptions`, which want the unfiltered
    "every skill's latest version" shape rather than a paginated search result."""
    entries, total = search(
        session, query, namespace=namespace, author=author, tags=tags, sort=sort, page=page, page_size=page_size
    )
    return summaries_from_entries(session, entries), total


def get_skill_detail(
    session: Session,
    cfg: SkillifyConfig,
    namespace: str,
    name: str,
    version: str | None = None,
    *,
    username: str | None = None,
) -> SkillDetail | None:
    versions = get_versions(session, namespace, name)  # newest first
    if not versions:
        return None
    if version is None:
        # C-1: default ("no version pinned") means "latest non-yanked" — a yanked newest
        # version should not be what a plain GET .../{namespace}/{name} silently serves.
        # Explicitly requesting a version (below) bypasses this and can return a yanked one.
        latest = next((v for v in versions if not v.yanked), None)
        if latest is None:
            return None
    else:
        latest = next((v for v in versions if v.version == version), None)
        if latest is None:
            return None

    readme: str | None = None
    skill_md: str | None = None
    tarball_url: str | None = None
    checksum_url: str | None = None

    if cfg.forgejo_url and cfg.forgejo_token:
        org = cfg.forgejo_org or namespace
        tag = f"v{latest.version}"
        client = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
        try:
            readme = client.get_raw_file(org, name, "README.md", tag)
            skill_md = client.get_raw_file(org, name, "SKILL.md", tag)
            release = client.get_release_by_tag(org, name, tag)
            if release is not None:
                expected_stem = f"{namespace}-{name}-{latest.version}"
                tarball = next((a for a in release.assets if a.name == f"{expected_stem}.tar.gz"), None)
                checksum = next((a for a in release.assets if a.name == f"{expected_stem}.sha256"), None)
                tarball_url = tarball.browser_download_url if tarball else None
                checksum_url = checksum.browser_download_url if checksum else None
        except ForgejoError:
            pass  # best-effort enrichment — index data alone is still a valid response

    rating_avg, rating_count = rating_stats(session).get((namespace, name), (None, 0))
    star_count = star_counts(session).get((namespace, name), 0)
    starred = (
        has_starred(session, namespace=namespace, name=name, author=username)
        if username is not None
        else False
    )
    subscribed = (
        is_subscribed(session, namespace=namespace, name=name, author=username)
        if username is not None
        else False
    )

    governance = dict(latest.governance or {})
    if not isinstance(governance, dict):
        governance = {}
    workflow_id = governance.pop("workflowId", None)
    if isinstance(workflow_id, str):
        from sqlalchemy import select
        from skillify.evals import aggregate_task_metrics
        from skillify.index.models import EndpointTaskEventRecord, EndpointTaskRecord

        rows = session.execute(
            select(EndpointTaskEventRecord, EndpointTaskRecord.task_id)
            .join(EndpointTaskRecord, EndpointTaskRecord.task_id == EndpointTaskEventRecord.task_id)
            .where(
                EndpointTaskRecord.workflow_id == workflow_id,
                EndpointTaskRecord.workflow_version == latest.version,
            )
        ).all()
        metrics = aggregate_task_metrics({
            "eventId": event.event_id,
            "eventType": event.event_type,
            "taskId": task_id,
            "testSummary": event.test_summary,
            "reasonCode": event.failure_reason,
        } for event, task_id in rows)
        governance.update({
            "successRate": metrics["successRate"],
            "testPassRate": metrics["testPassRate"],
            "sampleSize": metrics["completedTasks"],
            "failureReasons": metrics["blockedReasons"],
        })
    return SkillDetail(
        namespace=latest.namespace,
        name=latest.name,
        version=latest.version,
        description=latest.description,
        author=latest.author,
        tags=latest.tags,
        publishedAt=latest.published_at,
        versions=[v.version for v in versions],
        readme=readme,
        skillMd=skill_md,
        tarballUrl=tarball_url,
        checksumUrl=checksum_url,
        installCommand=install_command(namespace, name),
        agentPrompt=agent_prompt(namespace, name, cfg),
        installCount=install_counts(session).get((namespace, name), 0),
        ratingAverage=rating_avg,
        ratingCount=rating_count,
        starCount=star_count,
        starred=starred,
        subscribed=subscribed,
        governance=governance,
    )


def list_versions(
    session: Session, cfg: SkillifyConfig, namespace: str, name: str
) -> list[VersionInfo]:
    """C-1 version timeline — every published version (yanked or not), with `releaseNotes`
    fetched best-effort from the matching Forgejo release body. Forgejo being unconfigured
    or a tag lookup failing just leaves `releaseNotes` as `None`; it never fails the whole
    endpoint (same best-effort spirit as `get_skill_detail`'s README/tarball enrichment)."""
    versions = get_versions(session, namespace, name)  # newest first

    client: ForgejoClient | None = None
    org = cfg.forgejo_org or namespace
    if cfg.forgejo_url and cfg.forgejo_token:
        client = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)

    infos = []
    for v in versions:
        release_notes: str | None = None
        if client is not None:
            try:
                release = client.get_release_by_tag(org, name, f"v{v.version}")
                if release is not None:
                    release_notes = release.body
            except ForgejoError:
                pass
        infos.append(
            VersionInfo(version=v.version, publishedAt=v.published_at, yanked=v.yanked, releaseNotes=release_notes)
        )
    return infos


def diff_versions(
    cfg: SkillifyConfig, namespace: str, name: str, from_version: str, to_version: str
) -> VersionDiff:
    """C-1 — pure computation, nothing persisted: diffs the file trees of two tags via
    Forgejo's recursive git tree API. A path present in only one tree is added/removed; a
    path present in both with a different `sha` is modified."""
    if not cfg.forgejo_url or not cfg.forgejo_token:
        raise ForgejoError("forgejo_url/forgejo_token not configured")

    org = cfg.forgejo_org or namespace
    client = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    from_tree = {e["path"]: e.get("sha") for e in client.list_tree(org, name, f"v{from_version}") if e.get("type") == "blob"}
    to_tree = {e["path"]: e.get("sha") for e in client.list_tree(org, name, f"v{to_version}") if e.get("type") == "blob"}

    added = sorted(p for p in to_tree if p not in from_tree)
    removed = sorted(p for p in from_tree if p not in to_tree)
    modified = sorted(p for p in from_tree if p in to_tree and from_tree[p] != to_tree[p])
    return VersionDiff(added=added, removed=removed, modified=modified)
