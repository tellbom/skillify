"""C-2 — "My Skills" workspace aggregation: skills I authored, namespaces I own, and my
usage stats. Read-only queries over the existing `skill_index`/`skill_namespace_owners`/
`skill_events` tables — no new tables here (that's `publish_jobs.py`'s job).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from skillify.index.events import install_counts
from skillify.index.models import SkillIndexEntry, SkillNamespaceOwner
from skillify.index.queries import list_latest


def list_my_skills(session: Session, username: str) -> list[SkillIndexEntry]:
    """Latest version of each skill authored by `username` — reuses `list_latest`'s
    "most recent non-yanked version per (namespace, name)" grouping rather than
    re-deriving it, then filters to this author."""
    return [entry for entry in list_latest(session) if entry.author == username]


def list_my_namespaces(session: Session, username: str) -> list[SkillNamespaceOwner]:
    """Namespaces first-claimed (and thus owned) by `username` via the web-upload path."""
    stmt = select(SkillNamespaceOwner).where(SkillNamespaceOwner.owner_username == username)
    return list(session.execute(stmt).scalars())


def my_usage_stats(session: Session, username: str) -> dict:
    """Aggregate install-count stats across every skill authored by `username` — just
    enough for a "My Skills" page summary card, not a full analytics dashboard."""
    counts = install_counts(session)
    my_skills = list_my_skills(session, username)
    per_skill = {
        f"{entry.namespace}/{entry.name}": counts.get((entry.namespace, entry.name), 0) for entry in my_skills
    }
    return {
        "totalSkills": len(my_skills),
        "totalInstalls": sum(per_skill.values()),
        "installsBySkill": per_skill,
    }
