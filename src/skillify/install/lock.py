"""Lock file schema + read/write helpers (T1.4)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SkillLock:
    namespace: str
    name: str
    version: str
    sha256: str
    source: str  # URL or path the artifact was fetched from
    installedAt: str  # ISO 8601 timestamp, stamped by the caller (not this module)
    venvPath: str | None = None
    pythonDeps: list[str] = field(default_factory=list)
    skillDeps: list[str] = field(default_factory=list)  # resolved "namespace/name@version" list
    declaredTargets: list[str] = field(default_factory=list)  # manifest's own `targets` field
    targets: list[str] = field(default_factory=list)  # agent targets currently projected (T1.4a)

    @property
    def identifier(self) -> str:
        return f"{self.namespace}/{self.name}"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=False) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "SkillLock":
        return cls(**json.loads(text))


def lock_path(locks_dir: Path, namespace: str, name: str) -> Path:
    return locks_dir / f"{namespace}__{name}.json"


def read_lock(locks_dir: Path, namespace: str, name: str) -> SkillLock | None:
    path = lock_path(locks_dir, namespace, name)
    if not path.is_file():
        return None
    return SkillLock.from_json(path.read_text(encoding="utf-8"))


def write_lock(locks_dir: Path, lock: SkillLock) -> Path:
    locks_dir.mkdir(parents=True, exist_ok=True)
    path = lock_path(locks_dir, lock.namespace, lock.name)
    path.write_text(lock.to_json(), encoding="utf-8")
    return path


def remove_lock(locks_dir: Path, namespace: str, name: str) -> None:
    path = lock_path(locks_dir, namespace, name)
    path.unlink(missing_ok=True)


def list_locks(locks_dir: Path) -> list[SkillLock]:
    if not locks_dir.is_dir():
        return []
    return [
        SkillLock.from_json(p.read_text(encoding="utf-8"))
        for p in sorted(locks_dir.glob("*.json"))
    ]
