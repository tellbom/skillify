"""Aggregation logic: Postgres index (T2.2) + Forgejo (README/SKILL.md, release assets) (T3.1)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from skillify.common.config import SkillifyConfig
from skillify.index.events import install_counts
from skillify.index.models import SkillIndexEntry
from skillify.index.queries import get_versions, list_latest, search
from skillify.index.ratings import rating_stats
from skillify.publish.forgejo_client import ForgejoClient, ForgejoError
from skillify.web.schemas import SkillDetail, SkillSummary


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


def _summary_from_entry(entry: SkillIndexEntry) -> SkillSummary:
    return SkillSummary(
        namespace=entry.namespace,
        name=entry.name,
        version=entry.version,
        description=entry.description,
        author=entry.author,
        tags=entry.tags,
        publishedAt=entry.published_at,
    )


def list_skills(session: Session, query: str | None = None) -> list[SkillSummary]:
    entries = search(session, query) if query else list_latest(session)
    return [_summary_from_entry(e) for e in entries]


def get_skill_detail(
    session: Session, cfg: SkillifyConfig, namespace: str, name: str
) -> SkillDetail | None:
    versions = get_versions(session, namespace, name)  # newest first
    if not versions:
        return None
    latest = versions[0]

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
    )
