"""Deterministic, ownership-safe OpenCode capability projection.

The planner is pure with respect to mutation: it reads an injected artifact,
scope and lock store and returns an immutable preview.  Apply revalidates every
precondition under a local transaction lock before changing any target.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

import yaml

from skillify.agent.capability_lock import (
    CapabilityKind,
    CapabilityLock,
    CapabilityLockStore,
    GeneratedOwnership,
    InstallScope,
    LockedDependency,
)
from skillify.agent.permissions import MergedPermissions, summarize_permissions
from skillify.agent.codegraph import mcp_environment
from skillify.install.resolver import Coordinate
from skillify.mcp.registry import McpRegistry, render_opencode_mcp
from skillify.validator import validate_skill_dir


class OpenCodeConfigError(RuntimeError):
    """Base adapter failure."""


class OpenCodeConfigConflict(OpenCodeConfigError):
    """A target is unowned, modified, unsafe, or changed after planning."""


class MutationKind(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    UNCHANGED = "unchanged"


_ANY_PRECONDITION = object()


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _pointer_name(pointer: str) -> str:
    prefix = "/mcp/"
    if not pointer.startswith(prefix):
        raise OpenCodeConfigError("adapter owns only /mcp/<name> JSON pointers")
    return pointer[len(prefix):].replace("~1", "/").replace("~0", "~")


@dataclass(frozen=True)
class OpenCodeScopePaths:
    root: Path
    scope: InstallScope
    config_root: Path
    cache_root: Path
    workspace: Path

    @classmethod
    def user(cls, config_root: Path, *, cache_root: Path | None = None) -> "OpenCodeScopePaths":
        config = Path(config_root).absolute()
        return cls(
            root=config,
            scope=InstallScope.USER,
            config_root=config,
            cache_root=Path(cache_root).absolute() if cache_root is not None else config.parent / ".skillify-agent-cache",
            workspace=config,
        )

    @classmethod
    def project(cls, project_root: Path, *, cache_root: Path | None = None) -> "OpenCodeScopePaths":
        root = Path(project_root).absolute()
        return cls(
            root=root,
            scope=InstallScope.PROJECT,
            config_root=root / ".opencode",
            cache_root=Path(cache_root).absolute() if cache_root is not None else root / ".skillify-agent-cache",
            workspace=root,
        )

    @property
    def skills(self) -> Path:
        return self.config_root / "skills"

    @property
    def agents(self) -> Path:
        return self.config_root / "agents"

    @property
    def commands(self) -> Path:
        return self.config_root / "commands"

    @property
    def plugins(self) -> Path:
        return self.config_root / "plugins"

    @property
    def config_file(self) -> Path:
        return self.config_root / "opencode.json"

    def relative(self, path: Path) -> str:
        try:
            relative = Path(path).absolute().relative_to(self.root)
        except ValueError as exc:
            raise OpenCodeConfigError("generated target escapes its injected scope root") from exc
        return relative.as_posix()


@dataclass(frozen=True)
class CapabilitySource:
    root: Path
    coordinate: Coordinate
    forgejo_release: str
    commit: str
    checksum: str
    dependencies: tuple[LockedDependency, ...]
    permissions: MergedPermissions

    def load_validated_manifest(self) -> dict[str, Any]:
        root = Path(self.root).absolute()
        result = validate_skill_dir(root, check_directory_name=False)
        if not result.ok:
            detail = "; ".join(str(issue) for issue in result.issues)
            raise OpenCodeConfigError(f"invalid capability artifact: {detail}")
        try:
            value = yaml.safe_load((root / "skill.yaml").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise OpenCodeConfigError("capability manifest cannot be read safely") from exc
        namespace, name = self.coordinate.identifier.split("/", 1)
        if (
            not isinstance(value, dict)
            or value.get("namespace") != namespace
            or value.get("name") != name
            or value.get("version") != self.coordinate.version
        ):
            raise OpenCodeConfigError("capability source identity does not match its manifest")
        return value


@dataclass(frozen=True)
class OwnedMutation:
    path: str
    json_pointer: str | None
    kind: MutationKind
    content: bytes | None
    previous_sha256: str | None

    @property
    def ownership_key(self) -> tuple[str, str]:
        return (self.path, self.json_pointer or "")

    @property
    def sha256(self) -> str | None:
        return None if self.content is None else _sha(self.content)


@dataclass(frozen=True)
class OpenCodeInstallPlan:
    coordinate: Coordinate
    scope: InstallScope
    paths: OpenCodeScopePaths = field(repr=False, compare=False)
    lock_store: CapabilityLockStore = field(repr=False, compare=False)
    mutations: tuple[OwnedMutation, ...]
    permission_summary: Mapping[str, Any]
    resulting_lock: CapabilityLock
    expected_current_digest: str | None


@dataclass(frozen=True)
class OpenCodeUninstallPlan:
    lock: CapabilityLock
    paths: OpenCodeScopePaths = field(repr=False, compare=False)
    lock_store: CapabilityLockStore = field(repr=False, compare=False)
    mutations: tuple[OwnedMutation, ...]
    expected_current_digest: str


@dataclass(frozen=True)
class OpenCodeApplyResult:
    changed: bool
    lock: CapabilityLock
    mutations: tuple[OwnedMutation, ...]


def _safe_source_bytes(root: Path, relative: str) -> bytes:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise OpenCodeConfigError("entrypoint path is not a normalized relative file")
    root = root.absolute()
    directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        for part in pure.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(pure.parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise OpenCodeConfigError("entrypoint must be a regular file")
            with os.fdopen(file_fd, "rb") as handle:
                file_fd = -1
                return handle.read()
        finally:
            if file_fd >= 0:
                os.close(file_fd)
    except OSError as exc:
        raise OpenCodeConfigError("entrypoint is missing, symlinked, or unsafe") from exc
    finally:
        os.close(directory_fd)


def _target_state(paths: OpenCodeScopePaths, relative: str) -> bytes | None:
    try:
        descriptor, name = _open_target_parent(paths, relative, create=False)
    except FileNotFoundError:
        return None
    file_descriptor: int | None = None
    try:
        try:
            file_descriptor = os.open(
                name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor
            )
        except FileNotFoundError:
            return None
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OpenCodeConfigConflict(
                f"target is symlinked or not a regular file: {relative}"
            )
        with os.fdopen(file_descriptor, "rb") as handle:
            file_descriptor = None
            return handle.read()
    except OSError as exc:
        raise OpenCodeConfigConflict(f"target cannot be read safely: {relative}") from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        os.close(descriptor)


def _reject_duplicate_json_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise OpenCodeConfigConflict(f"existing opencode.json has duplicate key: {key}")
        value[key] = item
    return value


def _reject_nonfinite_json(value: str) -> object:
    raise OpenCodeConfigConflict(f"existing opencode.json has non-finite number: {value}")


def _read_config(paths: OpenCodeScopePaths) -> tuple[bytes | None, dict[str, Any]]:
    relative = paths.relative(paths.config_file)
    content = _target_state(paths, relative)
    if content is None:
        return None, {}
    try:
        value = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_json_fields,
            parse_constant=_reject_nonfinite_json,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise OpenCodeConfigConflict("existing opencode.json is invalid") from exc
    if type(value) is not dict:
        raise OpenCodeConfigConflict("existing opencode.json must be an object")
    if "mcp" in value and type(value["mcp"]) is not dict:
        raise OpenCodeConfigConflict("existing opencode.json mcp key must be an object")
    return content, value


def _owned_map(lock: CapabilityLock | None) -> dict[tuple[str, str | None], GeneratedOwnership]:
    return {} if lock is None else {(item.path, item.json_pointer): item for item in lock.generated}


def _current_for(source: CapabilitySource, paths: OpenCodeScopePaths, store: CapabilityLockStore) -> CapabilityLock | None:
    namespace, name = source.coordinate.identifier.split("/", 1)
    current = store.read_current(source.coordinate.kind, namespace, name)
    if current is not None and current.scope is not paths.scope:
        raise OpenCodeConfigConflict("current capability lock belongs to a different install scope")
    return current


def _file_mutation(
    *, paths: OpenCodeScopePaths, path: Path, content: bytes,
    owned: Mapping[tuple[str, str | None], GeneratedOwnership],
) -> OwnedMutation:
    relative = paths.relative(path)
    current = _target_state(paths, relative)
    ownership = owned.get((relative, None))
    if current is not None and ownership is None:
        raise OpenCodeConfigConflict(f"target is not owned by Skillify: {relative}")
    if ownership is not None:
        if current is None or _sha(current) != ownership.sha256:
            raise OpenCodeConfigConflict(f"owned target was modified: {relative}")
        kind = MutationKind.UNCHANGED if current == content else MutationKind.UPDATE
        return OwnedMutation(relative, None, kind, content, ownership.sha256)
    return OwnedMutation(relative, None, MutationKind.CREATE, content, None)


def _entrypoint_maps(manifest: Mapping[str, Any]) -> Mapping[str, Mapping[str, str]]:
    entrypoints = manifest.get("entrypoints") or {}
    if not isinstance(entrypoints, dict):
        raise OpenCodeConfigError("entrypoints must be an object")
    return entrypoints


def plan_install(
    source: CapabilitySource, *, paths: OpenCodeScopePaths,
    lock_store: CapabilityLockStore, mcp_registry: McpRegistry, installed_at: str,
) -> OpenCodeInstallPlan:
    if not isinstance(source, CapabilitySource) or not isinstance(paths, OpenCodeScopePaths):
        raise TypeError("source and paths must use the OpenCode adapter types")
    manifest = source.load_validated_manifest()
    current = _current_for(source, paths, lock_store)
    owned = _owned_map(current)
    root = Path(source.root).absolute()
    mutations: list[OwnedMutation] = []
    mutations.append(_file_mutation(
        paths=paths,
        path=paths.skills / str(manifest["name"]) / "SKILL.md",
        content=_safe_source_bytes(root, "SKILL.md"), owned=owned,
    ))
    entries = _entrypoint_maps(manifest)
    destinations = {"agents": paths.agents, "commands": paths.commands, "plugins": paths.plugins}
    for kind, base in destinations.items():
        for name, relative in sorted((entries.get(kind) or {}).items()):
            suffix = PurePosixPath(relative).suffix if kind == "plugins" else ".md"
            mutations.append(_file_mutation(
                paths=paths, path=base / f"{name}{suffix}",
                content=_safe_source_bytes(root, relative), owned=owned,
            ))

    _, config = _read_config(paths)
    mcp_values = config.get("mcp", {})
    assert isinstance(mcp_values, dict)
    for name, relative in sorted((entries.get("mcp") or {}).items()):
        sidecar = yaml.safe_load(_safe_source_bytes(root, relative).decode("utf-8"))
        if not isinstance(sidecar, dict):
            raise OpenCodeConfigError(f"MCP entrypoint {name} must be a metadata object")
        artifact = mcp_registry.get(str(sidecar.get("namespace")), str(sidecar.get("name")), str(sidecar.get("version")))
        fragment = _canonical_json(render_opencode_mcp(artifact))
        pointer = f"/mcp/{_pointer_escape(name)}"
        relative_config = paths.relative(paths.config_file)
        ownership = owned.get((relative_config, pointer))
        has_existing = name in mcp_values
        existing = mcp_values.get(name)
        if has_existing and ownership is None:
            raise OpenCodeConfigConflict(f"MCP key is not owned by Skillify: {pointer}")
        if ownership is not None:
            if not has_existing or _sha(_canonical_json(existing)) != ownership.sha256:
                raise OpenCodeConfigConflict(f"owned MCP key was modified: {pointer}")
            kind_value = MutationKind.UNCHANGED if _canonical_json(existing) == fragment else MutationKind.UPDATE
            mutations.append(OwnedMutation(relative_config, pointer, kind_value, fragment, ownership.sha256))
        else:
            mutations.append(OwnedMutation(relative_config, pointer, MutationKind.CREATE, fragment, None))

    desired_keys = {item.ownership_key for item in mutations}
    for ownership in current.generated if current is not None else ():
        key = (ownership.path, ownership.json_pointer or "")
        if key in desired_keys:
            continue
        if ownership.json_pointer is None:
            existing = _target_state(paths, ownership.path)
            if existing is None or _sha(existing) != ownership.sha256:
                raise OpenCodeConfigConflict(f"stale owned target was modified: {ownership.path}")
        else:
            name = _pointer_name(ownership.json_pointer)
            if name not in mcp_values:
                raise OpenCodeConfigConflict(f"stale owned MCP key was modified: {ownership.json_pointer}")
            existing = mcp_values[name]
            if _sha(_canonical_json(existing)) != ownership.sha256:
                raise OpenCodeConfigConflict(f"stale owned MCP key was modified: {ownership.json_pointer}")
        mutations.append(OwnedMutation(ownership.path, ownership.json_pointer, MutationKind.DELETE, None, ownership.sha256))

    mutations.sort(key=lambda item: item.ownership_key)
    generated = tuple(
        GeneratedOwnership(item.path, item.json_pointer, item.sha256)
        for item in mutations if item.kind is not MutationKind.DELETE and item.sha256 is not None
    )
    namespace, name = source.coordinate.identifier.split("/", 1)
    lock = CapabilityLock(
        schema_version=1, kind=source.coordinate.kind, namespace=namespace, name=name,
        version=source.coordinate.version, forgejo_release=source.forgejo_release,
        commit=source.commit, checksum=source.checksum, dependencies=source.dependencies,
        scope=paths.scope, generated=generated, installed_at=installed_at,
    )
    return OpenCodeInstallPlan(
        coordinate=source.coordinate, scope=paths.scope, paths=paths, lock_store=lock_store,
        mutations=tuple(mutations), permission_summary=summarize_permissions(source.permissions, paths.workspace),
        resulting_lock=lock, expected_current_digest=current.digest if current is not None else None,
    )


def _open_absolute_directory(path: Path, *, create: bool) -> int:
    absolute = Path(path).absolute()
    anchor = Path(absolute.anchor)
    descriptor = os.open(anchor, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        for part in absolute.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            next_descriptor = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_target_parent(paths: OpenCodeScopePaths, relative: str, *, create: bool) -> tuple[int, str]:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise OpenCodeConfigError("generated path is unsafe")
    descriptor = _open_absolute_directory(paths.root, create=create)
    try:
        for part in pure.parts[:-1]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            next_descriptor = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, pure.parts[-1]
    except BaseException:
        os.close(descriptor)
        raise


def _leaf_content(descriptor: int, name: str, relative: str) -> bytes | None:
    file_descriptor: int | None = None
    try:
        try:
            file_descriptor = os.open(
                name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor
            )
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise OpenCodeConfigConflict(f"target leaf became unsafe: {relative}")
        chunks: list[bytes] = []
        while chunk := os.read(file_descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)


def _check_leaf_precondition(
    descriptor: int, name: str, relative: str, expected_sha256: str | None | object
) -> None:
    if expected_sha256 is _ANY_PRECONDITION:
        return
    current = _leaf_content(descriptor, name, relative)
    if expected_sha256 is None:
        if current is not None:
            raise OpenCodeConfigConflict(f"stale plan: target appeared: {relative}")
    elif current is None or _sha(current) != expected_sha256:
        raise OpenCodeConfigConflict(f"stale plan: target changed: {relative}")


def _restore_displaced_leaf(
    descriptor: int, quarantine: str, name: str, relative: str
) -> None:
    """Restore a raced regular/symlink leaf without replacing a new racer.

    POSIX forbids hard-linking directories. Such a raced directory remains in
    the exact reported quarantine name so no user data is destroyed.
    """
    try:
        metadata = os.stat(quarantine, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            os.link(
                quarantine, name,
                src_dir_fd=descriptor, dst_dir_fd=descriptor,
                follow_symlinks=False,
            )
            os.unlink(quarantine, dir_fd=descriptor)
            raise OpenCodeConfigConflict(f"stale plan: target changed: {relative}")
    except FileExistsError as exc:
        raise OpenCodeConfigConflict(
            f"stale plan: displaced target preserved as {quarantine}: {relative}"
        ) from exc
    except OpenCodeConfigConflict:
        raise
    except OSError as exc:
        raise OpenCodeConfigConflict(
            f"stale plan: displaced target preserved as {quarantine}: {relative}"
        ) from exc
    raise OpenCodeConfigConflict(
        f"stale plan: displaced target preserved as {quarantine}: {relative}"
    )


def _atomic_target_write(
    paths: OpenCodeScopePaths,
    relative: str,
    content: bytes,
    *,
    expected_sha256: str | None | object = _ANY_PRECONDITION,
) -> None:
    descriptor, name = _open_target_parent(paths, relative, create=True)
    temporary = f".{name}.{secrets.token_hex(12)}.tmp"
    quarantine = f".{name}.{secrets.token_hex(12)}.old"
    file_descriptor: int | None = None
    quarantined = False
    try:
        try:
            existing = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and (stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode)):
            raise OpenCodeConfigConflict(f"target leaf became unsafe: {relative}")
        file_descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=descriptor,
        )
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_sha256 is None:
            try:
                os.link(
                    temporary, name,
                    src_dir_fd=descriptor, dst_dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise OpenCodeConfigConflict(
                    f"stale plan: target appeared: {relative}"
                ) from exc
            os.unlink(temporary, dir_fd=descriptor)
        elif expected_sha256 is _ANY_PRECONDITION:
            os.replace(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        else:
            try:
                os.rename(
                    name, quarantine,
                    src_dir_fd=descriptor, dst_dir_fd=descriptor,
                )
            except FileNotFoundError as exc:
                raise OpenCodeConfigConflict(
                    f"stale plan: target changed: {relative}"
                ) from exc
            quarantined = True
            try:
                displaced = _leaf_content(descriptor, quarantine, relative)
            except (OSError, OpenCodeConfigError) as exc:
                try:
                    _restore_displaced_leaf(
                        descriptor, quarantine, name, relative
                    )
                except OpenCodeConfigConflict as conflict:
                    quarantined = os.path.lexists(
                        paths.root / PurePosixPath(relative).parent / quarantine
                    )
                    raise conflict from exc
            if displaced is None or _sha(displaced) != expected_sha256:
                try:
                    os.link(
                        quarantine, name,
                        src_dir_fd=descriptor, dst_dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    os.unlink(quarantine, dir_fd=descriptor)
                    quarantined = False
                except FileExistsError:
                    pass
                raise OpenCodeConfigConflict(
                    f"stale plan: target changed; displaced content preserved as {quarantine}: {relative}"
                )
            try:
                os.link(
                    temporary, name,
                    src_dir_fd=descriptor, dst_dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                os.unlink(quarantine, dir_fd=descriptor)
                quarantined = False
                raise OpenCodeConfigConflict(
                    f"stale plan: target appeared: {relative}"
                ) from exc
            os.unlink(temporary, dir_fd=descriptor)
            os.unlink(quarantine, dir_fd=descriptor)
            quarantined = False
        os.fsync(descriptor)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        if quarantined:
            # A mismatched leaf is user data. It is deliberately retained under
            # the reported private sibling name when a racer occupied the
            # original name before it could be restored without clobbering.
            os.fsync(descriptor)
        os.close(descriptor)


def _target_unlink(
    paths: OpenCodeScopePaths,
    relative: str,
    *,
    expected_sha256: str | None | object = _ANY_PRECONDITION,
) -> None:
    try:
        descriptor, name = _open_target_parent(paths, relative, create=False)
    except FileNotFoundError:
        return
    try:
        try:
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OpenCodeConfigConflict(f"target leaf became unsafe: {relative}")
        if expected_sha256 is _ANY_PRECONDITION:
            os.unlink(name, dir_fd=descriptor)
        else:
            if expected_sha256 is None:
                raise OpenCodeConfigConflict(f"stale plan: target appeared: {relative}")
            quarantine = f".{name}.{secrets.token_hex(12)}.old"
            try:
                os.rename(
                    name, quarantine,
                    src_dir_fd=descriptor, dst_dir_fd=descriptor,
                )
            except FileNotFoundError as exc:
                raise OpenCodeConfigConflict(
                    f"stale plan: target changed: {relative}"
                ) from exc
            try:
                displaced = _leaf_content(descriptor, quarantine, relative)
            except (OSError, OpenCodeConfigError) as exc:
                try:
                    _restore_displaced_leaf(
                        descriptor, quarantine, name, relative
                    )
                except OpenCodeConfigConflict as conflict:
                    raise conflict from exc
            if displaced is None or _sha(displaced) != expected_sha256:
                try:
                    os.link(
                        quarantine, name,
                        src_dir_fd=descriptor, dst_dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    os.unlink(quarantine, dir_fd=descriptor)
                except FileExistsError:
                    pass
                raise OpenCodeConfigConflict(
                    f"stale plan: target changed; displaced content preserved as {quarantine}: {relative}"
                )
            os.unlink(quarantine, dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _transaction(paths: OpenCodeScopePaths) -> Iterator[None]:
    try:
        descriptor = _open_absolute_directory(paths.cache_root, create=True)
    except OSError as exc:
        raise OpenCodeConfigConflict("transaction path is symlinked or unsafe") from exc
    lock_descriptor: int | None = None
    try:
        os.fchmod(descriptor, 0o700)
        try:
            lock_descriptor = os.open(
                ".opencode-config.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=descriptor,
            )
        except OSError as exc:
            raise OpenCodeConfigConflict("transaction path is symlinked or unsafe") from exc
        os.fchmod(lock_descriptor, 0o600)
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        yield
    finally:
        if lock_descriptor is not None:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)
        os.close(descriptor)


def _current_for_plan(plan: OpenCodeInstallPlan) -> CapabilityLock | None:
    namespace, name = plan.coordinate.identifier.split("/", 1)
    return plan.lock_store.read_current(plan.coordinate.kind, namespace, name)


def _check_current_digest(actual: CapabilityLock | None, expected: str | None) -> None:
    digest = actual.digest if actual is not None else None
    if digest != expected:
        raise OpenCodeConfigConflict("stale install plan: ownership lock changed")


def _verify_mutations(paths: OpenCodeScopePaths, mutations: tuple[OwnedMutation, ...]) -> None:
    _, config = _read_config(paths)
    mcp = config.get("mcp", {})
    assert isinstance(mcp, dict)
    for mutation in mutations:
        if mutation.json_pointer is None:
            current = _target_state(paths, mutation.path)
            if mutation.previous_sha256 is None:
                if current is not None:
                    raise OpenCodeConfigConflict(f"stale plan: target appeared: {mutation.path}")
            elif current is None or _sha(current) != mutation.previous_sha256:
                raise OpenCodeConfigConflict(f"stale plan: target changed: {mutation.path}")
        else:
            name = _pointer_name(mutation.json_pointer)
            has_current = name in mcp
            current_value = mcp.get(name)
            if mutation.previous_sha256 is None:
                if has_current:
                    raise OpenCodeConfigConflict(f"stale plan: MCP key appeared: {mutation.json_pointer}")
            elif not has_current or _sha(_canonical_json(current_value)) != mutation.previous_sha256:
                raise OpenCodeConfigConflict(f"stale plan: MCP key changed: {mutation.json_pointer}")


def _whole_target_snapshots(
    paths: OpenCodeScopePaths, mutations: tuple[OwnedMutation, ...]
) -> dict[str, bytes | None]:
    paths_to_capture = {item.path for item in mutations if item.json_pointer is None}
    if any(item.json_pointer is not None for item in mutations):
        paths_to_capture.add(paths.relative(paths.config_file))
    return {path: _target_state(paths, path) for path in sorted(paths_to_capture)}


def _expected_target_states(
    paths: OpenCodeScopePaths,
    snapshots: Mapping[str, bytes | None],
    mutations: tuple[OwnedMutation, ...],
) -> dict[str, bytes | None]:
    expected = dict(snapshots)
    for mutation in mutations:
        if mutation.json_pointer is None and mutation.kind is not MutationKind.UNCHANGED:
            expected[mutation.path] = mutation.content
    json_mutations = tuple(
        item for item in mutations
        if item.json_pointer is not None and item.kind is not MutationKind.UNCHANGED
    )
    if json_mutations:
        relative = paths.relative(paths.config_file)
        original = snapshots.get(relative)
        config = {} if original is None else json.loads(original)
        mcp = dict(config.get("mcp", {}))
        for mutation in json_mutations:
            name = _pointer_name(mutation.json_pointer or "")
            if mutation.kind is MutationKind.DELETE:
                mcp.pop(name, None)
            else:
                assert mutation.content is not None
                mcp[name] = json.loads(mutation.content)
        if mcp:
            config["mcp"] = mcp
        else:
            config.pop("mcp", None)
        expected[relative] = (
            None if not config and original is None else _canonical_json(config)
        )
    return expected


def _restore_targets(
    paths: OpenCodeScopePaths,
    snapshots: Mapping[str, bytes | None],
    expected_states: Mapping[str, bytes | None],
) -> None:
    errors: list[BaseException] = []
    for path, content in reversed(tuple(snapshots.items())):
        try:
            current = _target_state(paths, path)
            if current == content:
                continue
            if current != expected_states.get(path):
                errors.append(OpenCodeConfigConflict(
                    f"transaction recovery preserved concurrently changed target: {path}"
                ))
                continue
            if content is None:
                assert current is not None
                _target_unlink(paths, path, expected_sha256=_sha(current))
            else:
                _atomic_target_write(
                    paths, path, content,
                    expected_sha256=None if current is None else _sha(current),
                )
        except BaseException as exc:  # restoration must attempt every target
            errors.append(exc)
    if errors:
        raise OpenCodeConfigError("transaction rollback could not restore every target") from errors[0]


def _apply_target_mutations(paths: OpenCodeScopePaths, mutations: tuple[OwnedMutation, ...]) -> bool:
    # Revalidate at the mutation boundary as well as at transaction entry so a
    # target created between planning/verification and apply is never silently
    # replaced.
    _verify_mutations(paths, mutations)
    changed = False
    for mutation in mutations:
        if mutation.json_pointer is not None or mutation.kind is MutationKind.UNCHANGED:
            continue
        changed = True
        if mutation.kind is MutationKind.DELETE:
            _target_unlink(
                paths, mutation.path, expected_sha256=mutation.previous_sha256
            )
        else:
            assert mutation.content is not None
            _atomic_target_write(
                paths, mutation.path, mutation.content,
                expected_sha256=mutation.previous_sha256,
            )

    json_mutations = tuple(item for item in mutations if item.json_pointer is not None)
    if json_mutations:
        original, config = _read_config(paths)
        mcp = dict(config.get("mcp", {}))
        json_changed = False
        for mutation in json_mutations:
            name = _pointer_name(mutation.json_pointer or "")
            if mutation.kind is MutationKind.UNCHANGED:
                continue
            json_changed = True
            if mutation.kind is MutationKind.DELETE:
                mcp.pop(name, None)
            else:
                assert mutation.content is not None
                mcp[name] = json.loads(mutation.content)
        if json_changed:
            changed = True
            if mcp:
                config["mcp"] = mcp
            else:
                config.pop("mcp", None)
            content = _canonical_json(config)
            relative = paths.relative(paths.config_file)
            if not config and original is None:
                pass
            else:
                # Ownership is at JSON-pointer granularity. Conservatively keep
                # an empty object because the adapter cannot prove that the
                # whole pre-existing file was created by Skillify.
                _atomic_target_write(
                    paths, relative, content,
                    expected_sha256=None if original is None else _sha(original),
                )
    return changed


def _snapshot_root(paths: OpenCodeScopePaths) -> Path:
    return paths.cache_root / "snapshots"


def _write_private_file(directory_fd: int, name: str, content: bytes) -> None:
    file_descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=directory_fd,
    )
    try:
        os.fchmod(file_descriptor, 0o600)
        view = memoryview(content)
        while view:
            written = os.write(file_descriptor, view)
            if written <= 0:
                raise OSError("snapshot write made no progress")
            view = view[written:]
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)


def _read_regular_file(directory_fd: int, name: str) -> bytes:
    file_descriptor = os.open(
        name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd
    )
    try:
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise OpenCodeConfigError("snapshot content is not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(file_descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(file_descriptor)


def _write_snapshot(paths: OpenCodeScopePaths, lock: CapabilityLock, mutations: tuple[OwnedMutation, ...]) -> None:
    root = _snapshot_root(paths)
    root_descriptor = _open_absolute_directory(root, create=True)
    os.fchmod(root_descriptor, 0o700)
    temporary_name = f".{lock.digest}.{secrets.token_hex(8)}.tmp"
    temporary_descriptor: int | None = None
    created_names: list[str] = []
    try:
        try:
            existing = os.stat(lock.digest, dir_fd=root_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISDIR(existing.st_mode):
                raise OpenCodeConfigError("snapshot directory is unsafe")
            os.close(root_descriptor)
            root_descriptor = -1
            _load_snapshot(paths, lock)
            return
        os.mkdir(temporary_name, 0o700, dir_fd=root_descriptor)
        temporary_descriptor = os.open(
            temporary_name,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_descriptor,
        )
        os.fchmod(temporary_descriptor, 0o700)
        by_key = {(item.path, item.json_pointer): item for item in mutations if item.content is not None}
        records: list[dict[str, object]] = []
        for index, ownership in enumerate(lock.generated):
            mutation = by_key.get((ownership.path, ownership.json_pointer))
            if mutation is None or mutation.content is None or _sha(mutation.content) != ownership.sha256:
                raise OpenCodeConfigError("snapshot content does not match resulting ownership")
            filename = f"{index:04d}.bin"
            _write_private_file(temporary_descriptor, filename, mutation.content)
            created_names.append(filename)
            records.append({
                "path": ownership.path, "jsonPointer": ownership.json_pointer,
                "sha256": ownership.sha256, "file": filename,
            })
        manifest = {"lockDigest": lock.digest, "generated": records}
        _write_private_file(temporary_descriptor, "manifest.json", _canonical_json(manifest))
        created_names.append("manifest.json")
        os.fsync(temporary_descriptor)
        os.rename(
            temporary_name, lock.digest,
            src_dir_fd=root_descriptor, dst_dir_fd=root_descriptor,
        )
        temporary_name = ""
        os.fsync(root_descriptor)
    except BaseException:
        if temporary_descriptor is not None:
            for filename in reversed(created_names):
                try:
                    os.unlink(filename, dir_fd=temporary_descriptor)
                except OSError:
                    pass
        if temporary_name:
            try:
                os.rmdir(temporary_name, dir_fd=root_descriptor)
            except OSError:
                pass
        raise
    finally:
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        if root_descriptor >= 0:
            os.close(root_descriptor)


def _load_snapshot(paths: OpenCodeScopePaths, lock: CapabilityLock) -> dict[tuple[str, str | None], bytes]:
    root_descriptor: int | None = None
    directory_descriptor: int | None = None
    try:
        root_descriptor = _open_absolute_directory(_snapshot_root(paths), create=False)
        directory_descriptor = os.open(
            lock.digest,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_descriptor,
        )
        manifest = json.loads(
            _read_regular_file(directory_descriptor, "manifest.json"),
            object_pairs_hook=_reject_duplicate_json_fields,
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, OpenCodeConfigError) as exc:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        if root_descriptor is not None:
            os.close(root_descriptor)
        raise OpenCodeConfigError("verified rollback snapshot is unavailable") from exc
    try:
        if type(manifest) is not dict or manifest.get("lockDigest") != lock.digest or type(manifest.get("generated")) is not list:
            raise OpenCodeConfigError("rollback snapshot metadata does not match the lock digest")
        expected = {(item.path, item.json_pointer): item.sha256 for item in lock.generated}
        result: dict[tuple[str, str | None], bytes] = {}
        expected_files = {"manifest.json"}
        for index, record in enumerate(manifest["generated"]):
            if type(record) is not dict or set(record) != {"path", "jsonPointer", "sha256", "file"}:
                raise OpenCodeConfigError("rollback snapshot metadata is malformed")
            key = (record["path"], record["jsonPointer"])
            filename = record["file"]
            if (
                key not in expected
                or expected[key] != record["sha256"]
                or filename != f"{index:04d}.bin"
            ):
                raise OpenCodeConfigError("rollback snapshot metadata conflicts with lock ownership")
            assert directory_descriptor is not None
            content = _read_regular_file(directory_descriptor, filename)
            if _sha(content) != expected[key]:
                raise OpenCodeConfigError("rollback snapshot checksum mismatch")
            result[key] = content
            expected_files.add(filename)
        if set(result) != set(expected) or set(os.listdir(directory_descriptor)) != expected_files:
            raise OpenCodeConfigError("rollback snapshot is incomplete or has unexpected content")
        return result
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        if root_descriptor is not None:
            os.close(root_descriptor)


def apply_install(plan: OpenCodeInstallPlan, *, dry_run: bool = False) -> OpenCodeApplyResult:
    if not isinstance(plan, OpenCodeInstallPlan):
        raise TypeError("plan must be an OpenCodeInstallPlan")
    if dry_run:
        return OpenCodeApplyResult(False, plan.resulting_lock, plan.mutations)
    with _transaction(plan.paths):
        previous_lock = _current_for_plan(plan)
        _check_current_digest(previous_lock, plan.expected_current_digest)
        _verify_mutations(plan.paths, plan.mutations)
        snapshots = _whole_target_snapshots(plan.paths, plan.mutations)
        expected_states = _expected_target_states(plan.paths, snapshots, plan.mutations)
        try:
            changed = _apply_target_mutations(plan.paths, plan.mutations)
            _write_snapshot(plan.paths, plan.resulting_lock, plan.mutations)
            plan.lock_store.write_current(plan.resulting_lock)
        except BaseException as exc:
            recovery_errors: list[BaseException] = []
            try:
                _restore_targets(plan.paths, snapshots, expected_states)
            except BaseException as recovery_exc:
                recovery_errors.append(recovery_exc)
            try:
                if previous_lock is None:
                    plan.lock_store.remove_current(plan.resulting_lock)
                else:
                    plan.lock_store.write_current(previous_lock)
            except BaseException as recovery_exc:
                recovery_errors.append(recovery_exc)
            if recovery_errors:
                raise OpenCodeConfigError(
                    "install rollback could not restore targets and ownership lock; "
                    f"original failure: {exc}; recovery: {recovery_errors[0]}"
                ) from recovery_errors[0]
            raise exc
        return OpenCodeApplyResult(changed, plan.resulting_lock, plan.mutations)


def plan_uninstall(
    lock: CapabilityLock, *, paths: OpenCodeScopePaths, lock_store: CapabilityLockStore,
) -> OpenCodeUninstallPlan:
    if not isinstance(lock, CapabilityLock) or lock.scope is not paths.scope:
        raise OpenCodeConfigConflict("uninstall lock does not belong to the selected scope")
    current = lock_store.read_current(lock.kind, lock.namespace, lock.name)
    if current is None or current.digest != lock.digest:
        raise OpenCodeConfigConflict("uninstall requires the exact current ownership lock")
    mutations: list[OwnedMutation] = []
    _, config = _read_config(paths)
    mcp = config.get("mcp", {})
    assert isinstance(mcp, dict)
    for ownership in lock.generated:
        if ownership.json_pointer is None:
            content = _target_state(paths, ownership.path)
            if content is None or _sha(content) != ownership.sha256:
                raise OpenCodeConfigConflict(f"owned target was modified: {ownership.path}")
        else:
            name = _pointer_name(ownership.json_pointer)
            if name not in mcp or _sha(_canonical_json(mcp[name])) != ownership.sha256:
                raise OpenCodeConfigConflict(f"owned MCP key was modified: {ownership.json_pointer}")
        mutations.append(OwnedMutation(
            ownership.path, ownership.json_pointer, MutationKind.DELETE, None, ownership.sha256,
        ))
    return OpenCodeUninstallPlan(lock, paths, lock_store, tuple(mutations), lock.digest)


def apply_uninstall(plan: OpenCodeUninstallPlan, *, dry_run: bool = False) -> OpenCodeApplyResult:
    if not isinstance(plan, OpenCodeUninstallPlan):
        raise TypeError("plan must be an OpenCodeUninstallPlan")
    if dry_run:
        return OpenCodeApplyResult(False, plan.lock, plan.mutations)
    with _transaction(plan.paths):
        current = plan.lock_store.read_current(plan.lock.kind, plan.lock.namespace, plan.lock.name)
        _check_current_digest(current, plan.expected_current_digest)
        _verify_mutations(plan.paths, plan.mutations)
        snapshots = _whole_target_snapshots(plan.paths, plan.mutations)
        expected_states = _expected_target_states(plan.paths, snapshots, plan.mutations)
        try:
            changed = _apply_target_mutations(plan.paths, plan.mutations)
            plan.lock_store.remove_current(plan.lock)
        except BaseException as exc:
            recovery_errors: list[BaseException] = []
            try:
                _restore_targets(plan.paths, snapshots, expected_states)
            except BaseException as recovery_exc:
                recovery_errors.append(recovery_exc)
            try:
                plan.lock_store.write_current(plan.lock)
            except BaseException as recovery_exc:
                recovery_errors.append(recovery_exc)
            if recovery_errors:
                raise OpenCodeConfigError(
                    "uninstall rollback could not restore targets and ownership lock; "
                    f"original failure: {exc}; recovery: {recovery_errors[0]}"
                ) from recovery_errors[0]
            raise exc
        return OpenCodeApplyResult(changed, plan.lock, plan.mutations)


def rollback_install(
    digest: str, *, paths: OpenCodeScopePaths, lock_store: CapabilityLockStore,
) -> OpenCodeApplyResult:
    target = lock_store.read_digest(digest)
    if target.scope is not paths.scope:
        raise OpenCodeConfigConflict("rollback lock does not belong to the selected scope")
    current = lock_store.read_current(target.kind, target.namespace, target.name)
    if current is None:
        raise OpenCodeConfigConflict("rollback requires a current ownership lock")
    content = _load_snapshot(paths, target)
    owned = _owned_map(current)
    mutations: list[OwnedMutation] = []
    for ownership in target.generated:
        previous = owned.get((ownership.path, ownership.json_pointer))
        if previous is None:
            if ownership.json_pointer is None:
                if _target_state(paths, ownership.path) is not None:
                    raise OpenCodeConfigConflict(f"rollback target is not owned: {ownership.path}")
            else:
                _, config = _read_config(paths)
                if _pointer_name(ownership.json_pointer) in config.get("mcp", {}):
                    raise OpenCodeConfigConflict(f"rollback MCP key is not owned: {ownership.json_pointer}")
            kind = MutationKind.CREATE
            previous_sha = None
        else:
            kind = MutationKind.UNCHANGED if previous.sha256 == ownership.sha256 else MutationKind.UPDATE
            previous_sha = previous.sha256
        mutations.append(OwnedMutation(
            ownership.path, ownership.json_pointer, kind,
            content[(ownership.path, ownership.json_pointer)], previous_sha,
        ))
    target_keys = {(item.path, item.json_pointer) for item in target.generated}
    for ownership in current.generated:
        if (ownership.path, ownership.json_pointer) not in target_keys:
            mutations.append(OwnedMutation(
                ownership.path, ownership.json_pointer, MutationKind.DELETE, None, ownership.sha256,
            ))
    mutations.sort(key=lambda item: item.ownership_key)
    plan = OpenCodeInstallPlan(
        coordinate=Coordinate(target.kind, f"{target.namespace}/{target.name}", target.version),
        scope=paths.scope, paths=paths, lock_store=lock_store, mutations=tuple(mutations),
        permission_summary={}, resulting_lock=target, expected_current_digest=current.digest,
    )
    return apply_install(plan)


def configure_codegraph_mcp(
    paths: OpenCodeScopePaths,
    *,
    executable: str = "codegraph",
    dry_run: bool = False,
) -> bool:
    """Add the pinned CodeGraph MCP entry without owning unrelated OpenCode config."""
    original, config = _read_config(paths)
    mcp = dict(config.get("mcp", {}))
    desired = {
        "type": "local",
        "command": [executable, "serve", "--mcp", "--path", str(paths.workspace.absolute())],
        "environment": mcp_environment(paths.workspace),
        "enabled": True,
    }
    existing = mcp.get("codegraph_explore")
    if existing is not None and existing != desired:
        raise OpenCodeConfigConflict("MCP key is not owned by Skillify: /mcp/codegraph_explore")
    if existing == desired:
        return False
    if dry_run:
        return True
    mcp["codegraph_explore"] = desired
    config["mcp"] = mcp
    relative = paths.relative(paths.config_file)
    _atomic_target_write(
        paths,
        relative,
        _canonical_json(config),
        expected_sha256=None if original is None else _sha(original),
    )
    return True


def render_task_mcp_config(servers: dict[str, dict[str, object]]) -> dict[str, object]:
    """Render only the already-selected per-task MCP subset for OpenCode."""
    return {"mcp": dict(servers)} if servers else {}
