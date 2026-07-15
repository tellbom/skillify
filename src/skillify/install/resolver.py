"""Resolve where to download a skill's artifact from — a Forgejo release (T1.4/C2).

C2 hardening: earlier versions grabbed the first `*.tar.gz`/`*.sha256` asset on a release,
which breaks (or worse, silently picks the wrong asset) the moment a release has more than
one tarball/checksum pair. This module now requires assets to match the exact basename the
packager (`packaging/pack.py`) produces — `<namespace>-<name>-<version>` — and cross-checks
against the `.artifact.json` sidecar's own declared identity/checksum when present.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, TypeVar

from skillify.agent.capability_lock import (
    CapabilityKind,
    CapabilityLockError,
    _coerce_enum,
    _validate_exact_version,
    _validate_hex,
    _validate_identifier,
)
from skillify.install.extract import sha256_file
from skillify.publish.forgejo_client import ForgejoClient, ForgejoError


class ResolveError(Exception):
    pass


@dataclass
class ResolvedArtifact:
    version: str
    tarball_url: str
    checksum_url: str | None


class CapabilityResolveError(ValueError):
    """An immutable release graph cannot be resolved safely."""


class CapabilityIntegrityError(ValueError):
    """A downloaded artifact does not match its locked identity."""


_T = TypeVar("_T")


def _resolve_validation(operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except CapabilityLockError as exc:
        raise CapabilityResolveError(str(exc)) from exc


@dataclass(frozen=True)
class Coordinate:
    kind: CapabilityKind
    identifier: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _resolve_validation(lambda: _coerce_enum(self.kind, CapabilityKind, "kind"))
        )
        object.__setattr__(
            self, "identifier", _resolve_validation(lambda: _validate_identifier(self.identifier))
        )
        object.__setattr__(
            self, "version", _resolve_validation(lambda: _validate_exact_version(self.version))
        )

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.identifier}@{self.version}"


@dataclass(frozen=True)
class ReleaseRecord:
    coordinate: Coordinate
    forgejo_release: str
    commit: str
    checksum: str
    dependencies: tuple[Coordinate, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.coordinate, Coordinate):
            raise CapabilityResolveError("release coordinate must be a Coordinate")
        if type(self.forgejo_release) is not str or self.forgejo_release != f"v{self.coordinate.version}":
            raise CapabilityResolveError("release must use an immutable Forgejo release v<exact-version> tag")
        object.__setattr__(
            self,
            "commit",
            _resolve_validation(lambda: _validate_hex(self.commit, 40, "commit")),
        )
        object.__setattr__(
            self,
            "checksum",
            _resolve_validation(lambda: _validate_hex(self.checksum, 64, "checksum")),
        )
        if not isinstance(self.dependencies, (tuple, list)) or not all(
            isinstance(item, Coordinate) for item in self.dependencies
        ):
            raise CapabilityResolveError("release dependencies must contain exact Coordinates")
        dependencies = tuple(
            sorted(self.dependencies, key=lambda item: (item.kind.value, item.identifier, item.version))
        )
        if len(set(dependencies)) != len(dependencies):
            raise CapabilityResolveError("release contains a duplicate dependency coordinate")
        object.__setattr__(self, "dependencies", dependencies)


class ReleaseCatalog(Protocol):
    def get(self, coordinate: Coordinate) -> ReleaseRecord | None:
        """Return the exact immutable release or ``None`` without selecting a version."""
        raise NotImplementedError


class _GraphResolver:
    def __init__(self, catalog: ReleaseCatalog) -> None:
        self._catalog = catalog
        self._selected: dict[tuple[CapabilityKind, str], str] = {}
        self._resolved: set[Coordinate] = set()
        self._stack: list[Coordinate] = []
        self._result: list[ReleaseRecord] = []

    def resolve(self, root: Coordinate) -> tuple[ReleaseRecord, ...]:
        if not isinstance(root, Coordinate):
            raise CapabilityResolveError("root must be an exact Coordinate")
        self._visit(root)
        return tuple(self._result)

    def _visit(self, coordinate: Coordinate) -> None:
        if coordinate in self._stack:
            start = self._stack.index(coordinate)
            cycle = self._stack[start:] + [coordinate]
            raise CapabilityResolveError(f"dependency cycle: {' -> '.join(map(str, cycle))}")

        identity = (coordinate.kind, coordinate.identifier)
        selected = self._selected.get(identity)
        if selected is not None and selected != coordinate.version:
            raise CapabilityResolveError(
                f"version conflict for {coordinate.kind.value}:{coordinate.identifier}: "
                f"{selected} != {coordinate.version}"
            )
        if coordinate in self._resolved:
            return
        self._selected[identity] = coordinate.version

        record = self._catalog.get(coordinate)
        if record is None:
            raise CapabilityResolveError(f"missing immutable release: {coordinate}")
        if not isinstance(record, ReleaseRecord) or record.coordinate != coordinate:
            raise CapabilityResolveError(f"catalog returned mismatched release for {coordinate}")

        self._stack.append(coordinate)
        try:
            for dependency in record.dependencies:
                self._visit(dependency)
        finally:
            self._stack.pop()
        self._resolved.add(coordinate)
        self._result.append(record)


def resolve_capability_graph(root: Coordinate, catalog: ReleaseCatalog) -> tuple[ReleaseRecord, ...]:
    """Resolve exact metadata depth-first, dependency-before-parent, without installing."""
    return _GraphResolver(catalog).resolve(root)


def verify_locked_artifact(path: Path, expected_checksum: str) -> str:
    """Verify a local artifact against its immutable lock and return its checksum."""
    try:
        expected = _validate_hex(expected_checksum, 64, "checksum")
    except CapabilityLockError as exc:
        raise CapabilityIntegrityError(str(exc)) from exc
    try:
        actual = sha256_file(path)
    except OSError as exc:
        raise CapabilityIntegrityError(f"cannot verify locked artifact: {exc}") from exc
    if not hmac.compare_digest(actual, expected):
        raise CapabilityIntegrityError(
            f"artifact checksum mismatch: expected sha256={expected}, got {actual}"
        )
    return actual


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
