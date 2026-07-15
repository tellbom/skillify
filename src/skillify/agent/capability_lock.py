"""Immutable capability identity and privately persisted installation history."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping


class CapabilityLockError(ValueError):
    """A capability lock or its local persistence is unsafe or malformed."""


class CapabilityKind(str, Enum):
    SKILL = "skill"
    WORKFLOW = "workflow"
    MCP = "mcp"


class InstallScope(str, Enum):
    USER = "user"
    PROJECT = "project"


_SEMVER_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER_RE = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    rf"(?:-{_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER})*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
_COORDINATE_PART_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z")
_HEX_40_RE = re.compile(r"[0-9a-f]{40}\Z")
_HEX_64_RE = re.compile(r"[0-9a-f]{64}\Z")


def _require_string(value: object, field: str) -> str:
    if type(value) is not str:
        raise CapabilityLockError(f"{field} must be a string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise CapabilityLockError(
            f"{field} must contain only valid UTF-8 Unicode scalar values"
        ) from exc
    return value


def _validate_exact_version(value: object) -> str:
    version = _require_string(value, "version")
    if not _SEMVER_RE.fullmatch(version):
        raise CapabilityLockError("version must be an exact semantic version")
    return version


def _validate_hex(value: object, length: int, field: str) -> str:
    text = _require_string(value, field)
    pattern = _HEX_40_RE if length == 40 else _HEX_64_RE
    if not pattern.fullmatch(text):
        raise CapabilityLockError(f"{field} must be lowercase {length}-hex")
    return text


def _validate_coordinate_part(value: object, field: str) -> str:
    text = _require_string(value, field)
    if not _COORDINATE_PART_RE.fullmatch(text):
        raise CapabilityLockError(f"{field} must be a safe capability coordinate segment")
    return text


def _validate_identifier(value: object) -> str:
    text = _require_string(value, "identifier")
    parts = text.split("/")
    if len(parts) != 2:
        raise CapabilityLockError("identifier must be namespace/name")
    _validate_coordinate_part(parts[0], "identifier namespace")
    _validate_coordinate_part(parts[1], "identifier name")
    return text


def _coerce_enum(value: object, enum_type: type[Enum], field: str) -> Any:
    if not isinstance(value, (str, enum_type)):
        raise CapabilityLockError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise CapabilityLockError(f"{field} must be one of: {allowed}") from exc


def _validate_json_pointer(value: object) -> str | None:
    if value is None:
        return None
    pointer = _require_string(value, "json_pointer")
    if not pointer.startswith("/") or re.search(r"~(?:[^01]|$)", pointer):
        raise CapabilityLockError("json_pointer must be a valid RFC-6901 JSON pointer")
    return pointer


def _validate_generated_path(value: object) -> str:
    path = _require_string(value, "generated path")
    if not path or "\\" in path or any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise CapabilityLockError("generated path must be a relative safe path")
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or str(pure) != path
        or any(part in ("", ".", "..") for part in pure.parts)
    ):
        raise CapabilityLockError("generated path must be a relative safe path")
    return path


def _validate_installed_at(value: object) -> str:
    text = _require_string(value, "installed_at")
    try:
        timestamp = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CapabilityLockError("installed_at must be an offset-aware UTC timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise CapabilityLockError("installed_at must be an offset-aware UTC timestamp")
    return timestamp.astimezone(timezone.utc).isoformat()


def _strict_object(value: object, fields: frozenset[str], label: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise CapabilityLockError(f"{label} must be a JSON object")
    keys = set(value)
    if keys != fields:
        missing = sorted(fields - keys)
        unknown = sorted(keys - fields)
        detail = []
        if missing:
            detail.append(f"missing fields: {missing}")
        if unknown:
            detail.append(f"unknown fields: {unknown}")
        raise CapabilityLockError(f"invalid {label}: {'; '.join(detail)}")
    return value


def _reject_duplicate_json_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CapabilityLockError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class LockedDependency:
    kind: CapabilityKind
    identifier: str
    version: str
    checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_enum(self.kind, CapabilityKind, "kind"))
        object.__setattr__(self, "identifier", _validate_identifier(self.identifier))
        object.__setattr__(self, "version", _validate_exact_version(self.version))
        object.__setattr__(self, "checksum", _validate_hex(self.checksum, 64, "checksum"))

    def _as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "identifier": self.identifier,
            "version": self.version,
            "checksum": self.checksum,
        }

    @classmethod
    def _from_dict(cls, value: object) -> "LockedDependency":
        data = _strict_object(value, frozenset({"kind", "identifier", "version", "checksum"}), "dependency")
        return cls(data["kind"], data["identifier"], data["version"], data["checksum"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class GeneratedOwnership:
    path: str
    json_pointer: str | None
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _validate_generated_path(self.path))
        object.__setattr__(self, "json_pointer", _validate_json_pointer(self.json_pointer))
        object.__setattr__(self, "sha256", _validate_hex(self.sha256, 64, "sha256"))

    def _as_dict(self) -> dict[str, object]:
        return {"path": self.path, "json_pointer": self.json_pointer, "sha256": self.sha256}

    @classmethod
    def _from_dict(cls, value: object) -> "GeneratedOwnership":
        data = _strict_object(value, frozenset({"path", "json_pointer", "sha256"}), "generated ownership")
        return cls(data["path"], data["json_pointer"], data["sha256"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class CapabilityLock:
    schema_version: int
    kind: CapabilityKind
    namespace: str
    name: str
    version: str
    forgejo_release: str
    commit: str
    checksum: str
    dependencies: tuple[LockedDependency, ...]
    scope: InstallScope
    generated: tuple[GeneratedOwnership, ...]
    installed_at: str

    _FIELDS = frozenset(
        {
            "schema_version", "kind", "namespace", "name", "version", "forgejo_release",
            "commit", "checksum", "dependencies", "scope", "generated", "installed_at",
        }
    )

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise CapabilityLockError("schema_version must be integer 1")
        object.__setattr__(self, "kind", _coerce_enum(self.kind, CapabilityKind, "kind"))
        object.__setattr__(self, "namespace", _validate_coordinate_part(self.namespace, "namespace"))
        object.__setattr__(self, "name", _validate_coordinate_part(self.name, "name"))
        object.__setattr__(self, "version", _validate_exact_version(self.version))
        release = _require_string(self.forgejo_release, "forgejo_release")
        if release != f"v{self.version}":
            raise CapabilityLockError("forgejo_release must be an immutable v<exact-version> tag")
        object.__setattr__(self, "forgejo_release", release)
        object.__setattr__(self, "commit", _validate_hex(self.commit, 40, "commit"))
        object.__setattr__(self, "checksum", _validate_hex(self.checksum, 64, "checksum"))
        if not isinstance(self.dependencies, (tuple, list)):
            raise CapabilityLockError("dependencies must be an array")
        if not all(isinstance(item, LockedDependency) for item in self.dependencies):
            raise CapabilityLockError("dependencies must contain LockedDependency values")
        dependencies = tuple(sorted(self.dependencies, key=lambda item: (item.kind.value, item.identifier, item.version)))
        dependency_keys = [(item.kind.value, item.identifier) for item in dependencies]
        if len(set(dependency_keys)) != len(dependency_keys):
            raise CapabilityLockError("duplicate dependency coordinate")
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "scope", _coerce_enum(self.scope, InstallScope, "scope"))
        if not isinstance(self.generated, (tuple, list)):
            raise CapabilityLockError("generated must be an array")
        if not all(isinstance(item, GeneratedOwnership) for item in self.generated):
            raise CapabilityLockError("generated must contain GeneratedOwnership values")
        generated = tuple(sorted(self.generated, key=lambda item: (item.path, item.json_pointer or "")))
        ownership_keys = [(item.path, item.json_pointer) for item in generated]
        if len(set(ownership_keys)) != len(ownership_keys):
            raise CapabilityLockError("duplicate generated ownership key")
        object.__setattr__(self, "generated", generated)
        object.__setattr__(self, "installed_at", _validate_installed_at(self.installed_at))

    def _as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "namespace": self.namespace,
            "name": self.name,
            "version": self.version,
            "forgejo_release": self.forgejo_release,
            "commit": self.commit,
            "checksum": self.checksum,
            "dependencies": [item._as_dict() for item in self.dependencies],
            "scope": self.scope.value,
            "generated": [item._as_dict() for item in self.generated],
            "installed_at": self.installed_at,
        }

    def to_json(self) -> str:
        return json.dumps(self._as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, text: str) -> "CapabilityLock":
        if type(text) is not str:
            raise CapabilityLockError("lock JSON must be text")
        try:
            value = json.loads(text, object_pairs_hook=_reject_duplicate_json_fields)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise CapabilityLockError(f"invalid lock JSON: {exc}") from exc
        data = _strict_object(value, cls._FIELDS, "capability lock")
        dependencies = data["dependencies"]
        generated = data["generated"]
        if type(dependencies) is not list:
            raise CapabilityLockError("dependencies must be a JSON array")
        if type(generated) is not list:
            raise CapabilityLockError("generated must be a JSON array")
        return cls(
            schema_version=data["schema_version"],  # type: ignore[arg-type]
            kind=data["kind"],  # type: ignore[arg-type]
            namespace=data["namespace"],  # type: ignore[arg-type]
            name=data["name"],  # type: ignore[arg-type]
            version=data["version"],  # type: ignore[arg-type]
            forgejo_release=data["forgejo_release"],  # type: ignore[arg-type]
            commit=data["commit"],  # type: ignore[arg-type]
            checksum=data["checksum"],  # type: ignore[arg-type]
            dependencies=tuple(LockedDependency._from_dict(item) for item in dependencies),
            scope=data["scope"],  # type: ignore[arg-type]
            generated=tuple(GeneratedOwnership._from_dict(item) for item in generated),
            installed_at=data["installed_at"],  # type: ignore[arg-type]
        )


class CapabilityLockStore:
    """Mode-private current locks plus content-addressed immutable history."""

    _DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    _FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)

    def __init__(self, root: Path) -> None:
        self.root = Path(root).absolute()

    def _relative_parts(self, path: Path) -> tuple[str, ...]:
        try:
            return path.relative_to(self.root).parts
        except ValueError as exc:
            raise CapabilityLockError("lock store path escapes its root") from exc

    @staticmethod
    def _unsafe_path_error(path: Path, exc: OSError) -> CapabilityLockError:
        return CapabilityLockError(f"lock store path is a symlink or unsafe component: {path}: {exc}")

    def _open_root(self, *, create: bool) -> int:
        anchor = Path(self.root.anchor)
        if self.root == anchor:
            raise CapabilityLockError("lock store root must not be the filesystem root")
        directory_fd = os.open(anchor, self._DIRECTORY_FLAGS)
        current = anchor
        try:
            for part in self.root.parts[1:]:
                current = current / part
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=directory_fd)
                    except FileExistsError:
                        pass
                try:
                    next_fd = os.open(part, self._DIRECTORY_FLAGS, dir_fd=directory_fd)
                except FileNotFoundError:
                    raise
                except OSError as exc:
                    raise self._unsafe_path_error(current, exc) from exc
                os.close(directory_fd)
                directory_fd = next_fd
            if create:
                os.fchmod(directory_fd, 0o700)
            return directory_fd
        except BaseException:
            os.close(directory_fd)
            raise

    def _open_directory(self, path: Path, *, create: bool) -> int:
        parts = self._relative_parts(path)
        directory_fd = self._open_root(create=create)
        try:
            current = self.root
            for part in parts:
                current = current / part
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=directory_fd)
                    except FileExistsError:
                        pass
                try:
                    next_fd = os.open(part, self._DIRECTORY_FLAGS, dir_fd=directory_fd)
                except FileNotFoundError:
                    raise
                except OSError as exc:
                    raise self._unsafe_path_error(current, exc) from exc
                os.close(directory_fd)
                directory_fd = next_fd
                if create:
                    os.fchmod(directory_fd, 0o700)
            return directory_fd
        except BaseException:
            os.close(directory_fd)
            raise

    def _open_parent(self, path: Path, *, create: bool) -> tuple[int, str]:
        parts = self._relative_parts(path)
        if not parts:
            raise CapabilityLockError("lock store file path must be below its root")
        return self._open_directory(path.parent, create=create), parts[-1]

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        root_fd = self._open_root(create=True)
        lock_fd: int | None = None
        try:
            try:
                lock_fd = os.open(
                    ".store.lock",
                    os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=root_fd,
                )
            except OSError as exc:
                raise self._unsafe_path_error(self.root / ".store.lock", exc) from exc
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield
        finally:
            if lock_fd is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            os.close(root_fd)

    def _coordinate_path(self, kind: CapabilityKind, namespace: str, name: str) -> Path:
        safe_kind = _coerce_enum(kind, CapabilityKind, "kind")
        safe_namespace = _validate_coordinate_part(namespace, "namespace")
        safe_name = _validate_coordinate_part(name, "name")
        return self.root / "current" / safe_kind.value / safe_namespace / f"{safe_name}.json"

    def _current_path(self, lock: CapabilityLock) -> Path:
        return self._coordinate_path(lock.kind, lock.namespace, lock.name)

    def _history_path(self, digest: str) -> Path:
        safe_digest = _validate_hex(digest, 64, "digest")
        return self.root / "history" / f"{safe_digest}.json"

    @staticmethod
    def _reject_leaf_symlink(directory_fd: int, name: str, path: Path) -> None:
        try:
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode):
            raise CapabilityLockError(f"lock store file is a symlink: {path}")

    def _write_atomic(self, path: Path, text: str, *, mode: int = 0o600) -> Path:
        directory_fd, name = self._open_parent(path, create=True)
        temporary_name = f".{name}.{secrets.token_hex(12)}.tmp"
        file_fd: int | None = None
        try:
            self._reject_leaf_symlink(directory_fd, name, path)
            file_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                mode,
                dir_fd=directory_fd,
            )
            os.fchmod(file_fd, mode)
            with os.fdopen(file_fd, "w", encoding="utf-8", newline="") as handle:
                file_fd = None
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            self._reject_leaf_symlink(directory_fd, name, path)
            os.replace(temporary_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        except BaseException:
            if file_fd is not None:
                os.close(file_fd)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(directory_fd)
        return path

    def _read_from_parent(self, directory_fd: int, name: str, path: Path) -> CapabilityLock:
        file_fd: int | None = None
        try:
            try:
                file_fd = os.open(name, self._FILE_FLAGS, dir_fd=directory_fd)
            except FileNotFoundError:
                raise
            except OSError as exc:
                raise self._unsafe_path_error(path, exc) from exc
            metadata = os.fstat(file_fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise CapabilityLockError(f"lock store path is not a regular file: {path}")
            try:
                with os.fdopen(file_fd, "r", encoding="utf-8") as handle:
                    file_fd = None
                    return CapabilityLock.from_json(handle.read())
            except UnicodeError as exc:
                raise CapabilityLockError(f"lock store file is not UTF-8: {path}") from exc
        finally:
            if file_fd is not None:
                os.close(file_fd)

    def _read(self, path: Path) -> CapabilityLock:
        directory_fd, name = self._open_parent(path, create=False)
        try:
            return self._read_from_parent(directory_fd, name, path)
        finally:
            os.close(directory_fd)

    def _try_read(self, path: Path) -> CapabilityLock | None:
        try:
            return self._read(path)
        except FileNotFoundError:
            return None

    def write_current(self, lock: CapabilityLock) -> Path:
        if not isinstance(lock, CapabilityLock):
            raise CapabilityLockError("lock must be a CapabilityLock")
        with self._exclusive_lock():
            history = self._history_path(lock.digest)
            existing = self._try_read(history)
            if existing is not None:
                if existing != lock:
                    raise CapabilityLockError(f"lock history digest collision: {lock.digest}")
            else:
                self._write_atomic(history, lock.to_json(), mode=0o600)
            return self._write_atomic(self._current_path(lock), lock.to_json(), mode=0o600)

    def read_current(self, kind: CapabilityKind, namespace: str, name: str) -> CapabilityLock | None:
        path = self._coordinate_path(kind, namespace, name)
        lock = self._try_read(path)
        if lock is None:
            return None
        expected = (_coerce_enum(kind, CapabilityKind, "kind"), namespace, name)
        actual = (lock.kind, lock.namespace, lock.name)
        if actual != expected:
            raise CapabilityLockError(
                f"current lock coordinate mismatch: expected {expected[0].value}:{namespace}/{name}, "
                f"got {lock.kind.value}:{lock.namespace}/{lock.name}"
            )
        return lock

    def read_digest(self, digest: str) -> CapabilityLock:
        lock = self._read(self._history_path(digest))
        if lock.digest != digest:
            raise CapabilityLockError(f"lock history checksum mismatch: {digest}")
        return lock

    def remove_current(self, lock: CapabilityLock) -> None:
        with self._exclusive_lock():
            path = self._current_path(lock)
            try:
                directory_fd, name = self._open_parent(path, create=False)
            except FileNotFoundError:
                return
            try:
                try:
                    current = self._read_from_parent(directory_fd, name, path)
                except FileNotFoundError:
                    return
                if current.digest != lock.digest:
                    raise CapabilityLockError(
                        f"requested lock {lock.digest} does not match current lock {current.digest}"
                    )
                self._reject_leaf_symlink(directory_fd, name, path)
                os.unlink(name, dir_fd=directory_fd)
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
