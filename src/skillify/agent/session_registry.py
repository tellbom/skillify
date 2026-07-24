"""Crash-safe local registry for provider sessions owned by skillctl."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any


class SessionRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def load(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                return {}
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("session registry root must be an object")
            return {str(key): dict(item) for key, item in value.items()}

    def put(self, worker_key: str, record: dict[str, Any]) -> None:
        with self._lock:
            values = self.load()
            values[worker_key] = record
            self._write(values)

    def remove(self, worker_key: str) -> None:
        with self._lock:
            values = self.load()
            values.pop(worker_key, None)
            self._write(values)

    def _write(self, values: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(values, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
