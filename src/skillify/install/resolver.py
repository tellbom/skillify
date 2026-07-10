"""Resolve where to download a skill's artifact from — a Forgejo release (T1.4/C2).

C2 hardening: earlier versions grabbed the first `*.tar.gz`/`*.sha256` asset on a release,
which breaks (or worse, silently picks the wrong asset) the moment a release has more than
one tarball/checksum pair. This module now requires assets to match the exact basename the
packager (`packaging/pack.py`) produces — `<namespace>-<name>-<version>` — and cross-checks
against the `.artifact.json` sidecar's own declared identity/checksum when present.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from skillify.publish.forgejo_client import ForgejoClient, ForgejoError


class ResolveError(Exception):
    pass


@dataclass
class ResolvedArtifact:
    version: str
    tarball_url: str
    checksum_url: str | None


def resolve_release_artifact(
    client: ForgejoClient, org: str, namespace: str, name: str, version: str | None
) -> ResolvedArtifact:
    repo = name
    if version:
        release = client.get_release_by_tag(org, repo, f"v{version}")
        if release is None:
            raise ResolveError(f"{org}/{repo}@{version}: no release found for tag v{version}")
        resolved_version = version
    else:
        release = client.get_latest_release(org, repo)
        if release is None:
            raise ResolveError(f"{org}/{repo}: has no releases yet")
        resolved_version = release.tag_name.removeprefix("v")

    expected_stem = f"{namespace}-{name}-{resolved_version}"
    asset_names = [a.name for a in release.assets]

    tarball = next((a for a in release.assets if a.name == f"{expected_stem}.tar.gz"), None)
    if tarball is None:
        raise ResolveError(
            f"{org}/{repo}@{release.tag_name}: no asset named '{expected_stem}.tar.gz' "
            f"(release assets: {asset_names or 'none'})"
        )
    checksum = next((a for a in release.assets if a.name == f"{expected_stem}.sha256"), None)
    artifact_manifest = next((a for a in release.assets if a.name == f"{expected_stem}.artifact.json"), None)

    if artifact_manifest is not None:
        try:
            raw = client.fetch_text(artifact_manifest.browser_download_url)
            data = json.loads(raw)
        except (ForgejoError, json.JSONDecodeError) as exc:
            raise ResolveError(
                f"{org}/{repo}@{release.tag_name}: found '{expected_stem}.artifact.json' but "
                f"could not read/parse it: {exc}"
            ) from exc
        mismatches = [
            f"{field}: expected {expected!r}, artifact.json says {data.get(field)!r}"
            for field, expected in (("namespace", namespace), ("name", name), ("version", resolved_version))
            if data.get(field) != expected
        ]
        if mismatches:
            raise ResolveError(
                f"{org}/{repo}@{release.tag_name}: '{expected_stem}.artifact.json' identity "
                f"mismatch: {'; '.join(mismatches)}"
            )

    return ResolvedArtifact(
        version=resolved_version,
        tarball_url=tarball.browser_download_url,
        checksum_url=checksum.browser_download_url if checksum else None,
    )
