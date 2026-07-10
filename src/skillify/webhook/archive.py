"""Fetch a Forgejo repo's source tree at a given ref and locate the skill root within it (T2.1b).

Reuses `install.extract.safe_extract` for the same path-traversal/symlink/device-file
protections applied to install artifacts — a source archive is also untrusted input from
the CLI's perspective (a compromised/misconfigured Forgejo, or a crafted repo).
"""

from __future__ import annotations

from pathlib import Path

from skillify.install.extract import safe_extract
from skillify.publish.forgejo_client import ForgejoClient


class ArchiveError(Exception):
    pass


def resolve_archive_root(extracted_dir: Path) -> Path:
    """Forgejo/Gitea archives typically wrap the tree in a single top-level directory
    (e.g. `reponame-<sha>/`). If `skill.yaml` isn't directly at the extracted root but the
    extraction produced exactly one subdirectory, descend into it; otherwise assume the
    archive really is flat and let downstream validation report the real problem."""
    if (extracted_dir / "skill.yaml").is_file():
        return extracted_dir
    entries = list(extracted_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extracted_dir


def fetch_and_extract_archive(
    client: ForgejoClient, owner: str, repo: str, ref: str, work_dir: Path
) -> Path:
    """Download `ref`'s source tarball from Forgejo, extract it under `work_dir`, and
    return the resolved skill root directory (see `resolve_archive_root`)."""
    tarball_path = work_dir / "source.tar.gz"
    client.download_archive(owner, repo, ref, tarball_path)

    extracted_dir = work_dir / "extracted"
    safe_extract(tarball_path, extracted_dir)
    return resolve_archive_root(extracted_dir)
