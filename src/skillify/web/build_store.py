"""Owner-bound, expiring filesystem storage for preview-first Skill builds."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from skillify.web.build_models import (
    BuildNotFound,
    BuildRecord,
    BuildRevisionConflict,
    BuildSourceType,
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
        build_dir = self.root / build_id
        workspace = build_dir / "workspace"
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
        return self._record(build_dir, metadata)

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
        record = self.load(build_id, owner)
        if record.revision != expected_revision:
            raise BuildRevisionConflict(record.revision)
        build_dir = record.workspace.parent
        metadata = self._read_metadata(build_dir)
        mutation(record.workspace, metadata)
        metadata["revision"] = record.revision + 1
        self._write_metadata(build_dir, metadata)
        return self._record(build_dir, metadata)

    def cleanup_expired(self) -> None:
        if not self.root.is_dir():
            return
        now = _as_utc(self.clock())
        for build_dir in self.root.iterdir():
            if not build_dir.is_dir():
                continue
            try:
                metadata = self._read_metadata(build_dir)
                expired = datetime.fromisoformat(metadata["expiresAt"]) <= now
            except (BuildNotFound, KeyError, TypeError, ValueError):
                expired = True
            if expired:
                shutil.rmtree(build_dir, ignore_errors=True)

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
            workspace=build_dir / "workspace",
            detected_facts=dict(metadata.get("detectedFacts") or {}),
            confirmed_fields=set(metadata.get("confirmedFields") or []),
        )
