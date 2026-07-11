"""C-1 version center: yank/unyank a published version.

Yanking flips `SkillIndexEntry.yanked` — it does not delete the row or the Forgejo release.
A yanked version drops out of "latest" resolution (`list_latest`/`search`/`leaderboard`,
see queries.py) but stays visible in `get_versions` (marked `yanked=True`) and stays
explicitly installable (CLI `skillctl install ns/name@version` and the web detail endpoint
with `?version=`) — crates.io-style semantics.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from skillify.index.models import SkillIndexEntry, SkillNamespaceOwner


class VersionNotFoundError(Exception):
    def __init__(self, namespace: str, name: str, version: str):
        super().__init__(f"{namespace}/{name}@{version} not found in index")
        self.namespace = namespace
        self.name = name
        self.version = version


def set_yanked(
    session: Session, *, namespace: str, name: str, version: str, yanked: bool
) -> SkillIndexEntry:
    entry = session.execute(
        select(SkillIndexEntry).where(
            SkillIndexEntry.namespace == namespace,
            SkillIndexEntry.name == name,
            SkillIndexEntry.version == version,
        )
    ).scalar_one_or_none()
    if entry is None:
        raise VersionNotFoundError(namespace, name, version)
    entry.yanked = yanked
    session.commit()
    return entry


def can_manage_version(session: Session, *, namespace: str, username: str) -> bool:
    """True if `username` owns `namespace` (see `SkillNamespaceOwner`, first-publish-wins).
    Author checks are the caller's job (compare `entry.author == username` directly — the
    author is already on the entry, no need to query for it here); this only covers the
    "or namespace owner" half of the "author or namespace owner" rule."""
    owner = session.execute(
        select(SkillNamespaceOwner).where(SkillNamespaceOwner.namespace == namespace)
    ).scalar_one_or_none()
    return owner is not None and owner.owner_username == username
