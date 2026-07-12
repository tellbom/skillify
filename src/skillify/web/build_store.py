"""Owner-bound, expiring filesystem storage for preview-first Skill builds."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from skillify.web.build_models import (
    BuildNotFound,
    BuildRecord,
    BuildRevisionConflict,
    BuildSourceType,
    BuildStateConflict,
)

Clock = Callable[[], datetime]
Mutation = Callable[[Path, dict[str, Any]], None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class BuildStore:
    def __init__(self, cache_dir: Path, *, ttl_seconds: int, clock: Clock = _utc_now):
        if ttl_seconds <= 0:
            raise ValueError("build ttl must be greater than zero")
        self.root = cache_dir / "skill-builds"
        self.ttl_seconds = ttl_seconds
        self.clock = clock

    def create(
        self,
        owner: str,
        source_type: BuildSourceType,
        *,
        detected_facts: dict[str, Any] | None = None,
        confirmed_fields: set[str] | None = None,
    ) -> BuildRecord:
        self.cleanup_expired()
        now = _as_utc(self.clock())
        build_id = uuid.uuid4().hex
        final_build_dir = self.root / build_id
        build_dir = self.root / f".{build_id}.tmp"
        workspace = build_dir / "revisions" / "1"
        try:
            workspace.mkdir(parents=True, exist_ok=False)
            metadata: dict[str, Any] = {
                "buildId": build_id,
                "owner": owner,
                "sourceType": source_type,
                "revision": 1,
                "status": "needs_input",
                "createdAt": now.isoformat(),
                "expiresAt": (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
                "detectedFacts": detected_facts or {},
                "confirmedFields": sorted(confirmed_fields or set()),
            }
            self._write_metadata(build_dir, metadata)
            build_dir.replace(final_build_dir)
            return self._record(final_build_dir, metadata)
        except Exception:
            shutil.rmtree(build_dir, ignore_errors=True)
            shutil.rmtree(final_build_dir, ignore_errors=True)
            raise

    def load(self, build_id: str, owner: str) -> BuildRecord:
        build_dir = self._build_dir(build_id)
        metadata = self._read_metadata(build_dir)
        now = _as_utc(self.clock())
        if metadata.get("owner") != owner:
            raise BuildNotFound("build not found")
        if datetime.fromisoformat(metadata["expiresAt"]) <= now:
            shutil.rmtree(build_dir, ignore_errors=True)
            raise BuildNotFound("build not found")
        return self._record(build_dir, metadata)

    def mutate(
        self,
        build_id: str,
        owner: str,
        expected_revision: int,
        mutation: Mutation,
    ) -> BuildRecord:
        initial = self.load(build_id, owner)
        build_dir = self._build_dir(initial.build_id)
        with self._operation_lock(build_dir):
            record = self.load(build_id, owner)
            if record.revision != expected_revision:
                raise BuildRevisionConflict(record.revision)
            if record.status in {"publishing", "published"}:
                raise BuildStateConflict(f"build is already {record.status}")
            metadata = self._read_metadata(build_dir)
            next_revision = record.revision + 1
            revisions_dir = build_dir / "revisions"
            target = revisions_dir / str(next_revision)
            temporary = revisions_dir / f".{next_revision}.{uuid.uuid4().hex}.tmp"
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(record.workspace, temporary)
            try:
                mutation(temporary, metadata)
                temporary.replace(target)
                metadata["revision"] = next_revision
                try:
                    self._write_metadata(build_dir, metadata)
                except Exception:
                    shutil.rmtree(target, ignore_errors=True)
                    raise
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
            for old_revision in revisions_dir.iterdir():
                if not old_revision.is_dir() or old_revision == target:
                    continue
                try:
                    revision_number = int(old_revision.name)
                except ValueError:
                    continue
                if not self._revision_has_readers(build_dir, revision_number):
                    shutil.rmtree(old_revision, ignore_errors=True)
            return self._record(build_dir, metadata)

    def transition_status(
        self,
        build_id: str,
        owner: str,
        expected_revision: int,
        *,
        allowed: set[str],
        status: str,
    ) -> BuildRecord:
        initial = self.load(build_id, owner)
        build_dir = self._build_dir(initial.build_id)
        with self._operation_lock(build_dir):
            record = self.load(build_id, owner)
            if record.revision != expected_revision:
                raise BuildRevisionConflict(record.revision)
            if record.status not in allowed:
                raise BuildStateConflict(f"build is already {record.status}")
            metadata = self._read_metadata(build_dir)
            metadata["status"] = status
            self._write_metadata(build_dir, metadata)
            return self._record(build_dir, metadata)

    @contextmanager
    def read_lease(self, build_id: str, owner: str):
        initial = self.load(build_id, owner)
        build_dir = self._build_dir(initial.build_id)
        lease_id = uuid.uuid4().hex
        with self._operation_lock(build_dir):
            record = self.load(build_id, owner)
            lease_dir = build_dir / "readers" / str(record.revision)
            lease_dir.mkdir(parents=True, exist_ok=True)
            marker = lease_dir / lease_id
            marker.write_text(str(os.getpid()), encoding="ascii")
        try:
            yield record
        finally:
            with self._operation_lock(build_dir):
                marker.unlink(missing_ok=True)
                if lease_dir.is_dir() and not any(lease_dir.iterdir()):
                    lease_dir.rmdir()
                readers_root = build_dir / "readers"
                if readers_root.is_dir() and not any(readers_root.iterdir()):
                    readers_root.rmdir()
                try:
                    current = self.load(build_id, owner)
                except BuildNotFound:
                    current = None
                if current is not None and current.revision != record.revision:
                    old_workspace = build_dir / "revisions" / str(record.revision)
                    if not self._revision_has_readers(build_dir, record.revision):
                        shutil.rmtree(old_workspace, ignore_errors=True)

    def delete(self, build_id: str, owner: str) -> None:
        record = self.load(build_id, owner)
        shutil.rmtree(self._build_dir(record.build_id), ignore_errors=True)

    def cleanup_expired(self) -> None:
        if not self.root.is_dir():
            return
        now = _as_utc(self.clock())
        for build_dir in self.root.iterdir():
            if not build_dir.is_dir():
                continue
            if build_dir.name.startswith("."):
                age = now.timestamp() - build_dir.stat().st_mtime
                if age > self.ttl_seconds:
                    shutil.rmtree(build_dir, ignore_errors=True)
                continue
            try:
                metadata = self._read_metadata(build_dir)
                expired = datetime.fromisoformat(metadata["expiresAt"]) <= now
            except (BuildNotFound, KeyError, TypeError, ValueError):
                expired = True
            if expired and not self._has_active_readers(build_dir, now):
                shutil.rmtree(build_dir, ignore_errors=True)

    def _has_active_readers(self, build_dir: Path, now: datetime) -> bool:
        readers_root = build_dir / "readers"
        if not readers_root.is_dir():
            return False
        stale_after = max(self.ttl_seconds, 300)
        active = False
        for marker in readers_root.rglob("*"):
            if not marker.is_file():
                continue
            age = now.timestamp() - marker.stat().st_mtime
            if age > stale_after:
                marker.unlink(missing_ok=True)
            else:
                active = True
        return active

    @staticmethod
    def _revision_has_readers(build_dir: Path, revision: int) -> bool:
        lease_dir = build_dir / "readers" / str(revision)
        return lease_dir.is_dir() and any(path.is_file() for path in lease_dir.iterdir())

    @staticmethod
    @contextmanager
    def _operation_lock(build_dir: Path):
        lock_path = build_dir / ".operation.lock"
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise BuildStateConflict("another operation is already changing this build") from exc
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            yield
        finally:
            os.close(descriptor)
            lock_path.unlink(missing_ok=True)

    def _build_dir(self, build_id: str) -> Path:
        try:
            normalized = uuid.UUID(build_id).hex
        except (ValueError, AttributeError, TypeError) as exc:
            raise BuildNotFound("build not found") from exc
        return self.root / normalized

    @staticmethod
    def _read_metadata(build_dir: Path) -> dict[str, Any]:
        try:
            value = json.loads((build_dir / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BuildNotFound("build not found") from exc
        if not isinstance(value, dict):
            raise BuildNotFound("build not found")
        return value

    @staticmethod
    def _write_metadata(build_dir: Path, metadata: dict[str, Any]) -> None:
        target = build_dir / "metadata.json"
        temporary = build_dir / "metadata.json.tmp"
        temporary.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(target)

    @staticmethod
    def _record(build_dir: Path, metadata: dict[str, Any]) -> BuildRecord:
        return BuildRecord(
            build_id=str(metadata["buildId"]),
            owner=str(metadata["owner"]),
            source_type=metadata["sourceType"],
            revision=int(metadata["revision"]),
            status=metadata["status"],
            created_at=datetime.fromisoformat(metadata["createdAt"]),
            expires_at=datetime.fromisoformat(metadata["expiresAt"]),
            workspace=build_dir / "revisions" / str(metadata["revision"]),
            detected_facts=dict(metadata.get("detectedFacts") or {}),
            confirmed_fields=set(metadata.get("confirmedFields") or []),
        )
