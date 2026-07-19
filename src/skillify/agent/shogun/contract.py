"""Defensive readers for the stable, file-based Shogun queue contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


TASK_STEMS = frozenset({*(f"ashigaru{i}" for i in range(1, 9)), "gunshi"})
REPORT_STEMS = frozenset({*(f"ashigaru{i}_report" for i in range(1, 9)), "gunshi_report"})
COMMAND_FILE = "shogun_to_karo.yaml"


class ShogunContractError(ValueError):
    pass


@dataclass(frozen=True)
class QueueItem:
    kind: str
    item_id: str
    status: str
    worker_id: str | None
    parent_id: str | None
    summary: str | None


def item_status(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    if value.get("status") is not None:
        return str(value["status"])
    legacy = value.get("task")
    if isinstance(legacy, dict) and legacy.get("status") is not None:
        return str(legacy["status"])
    return ""


def _load(path: Path) -> Any:
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ShogunContractError(f"invalid Shogun queue file: {Path(path).name}") from exc


def _text(value: object) -> str | None:
    return value.strip()[:300] if isinstance(value, str) and value.strip() else None


def _item(kind: str, value: dict[str, Any], fallback_id: str, worker_id: str | None) -> QueueItem:
    item_id = value.get("id") or value.get("task_id") or value.get("report_id") or fallback_id
    if not isinstance(item_id, str) or not item_id:
        raise ShogunContractError("Shogun queue item requires a stable identifier")
    parent = value.get("parent_cmd") or value.get("parent_id")
    if parent is not None and not isinstance(parent, str):
        parent = None
    summary = _text(value.get("summary") or value.get("message") or value.get("description"))
    return QueueItem(kind, item_id, item_status(value), worker_id, parent, summary)


def read_queue_file(path: Path) -> tuple[QueueItem, ...]:
    source = Path(path)
    data = _load(source)
    if source.name == COMMAND_FILE:
        if not isinstance(data, dict):
            raise ShogunContractError("Shogun command queue must be an object")
        commands = data.get("commands", data.get("queue", []))
        if not isinstance(commands, list):
            raise ShogunContractError("Shogun command queue entries must be a list")
        return tuple(
            _item("command", value, f"command-{index}", "coordinator")
            for index, value in enumerate(commands)
            if isinstance(value, dict)
        )
    parent = source.parent.name
    stem = source.stem
    if parent == "tasks" and stem in TASK_STEMS:
        if not isinstance(data, dict):
            raise ShogunContractError("Shogun task file must be an object")
        return (_item("task", data, stem, stem),)
    if parent == "reports" and stem in REPORT_STEMS:
        if not isinstance(data, dict):
            raise ShogunContractError("Shogun report file must be an object")
        worker = stem.removesuffix("_report")
        return (_item("report", data, stem, worker),)
    if parent == "inbox" and source.suffix == ".yaml" and stem:
        if not isinstance(data, dict):
            raise ShogunContractError("Shogun inbox file must be an object")
        entries = data.get("messages", data.get("inbox", []))
        if not isinstance(entries, list):
            return ()
        return tuple(
            _item("inbox", value, f"{stem}-{index}", stem)
            for index, value in enumerate(entries)
            if isinstance(value, dict)
        )
    raise ShogunContractError(f"non-canonical Shogun queue filename: {source.name}")


def scan_queue(queue_dir: Path) -> tuple[QueueItem, ...]:
    root = Path(queue_dir)
    paths = [root / COMMAND_FILE]
    for name, stems in (("tasks", TASK_STEMS), ("reports", REPORT_STEMS)):
        paths.extend(root / name / f"{stem}.yaml" for stem in sorted(stems))
    paths.extend(sorted((root / "inbox").glob("*.yaml")) if (root / "inbox").is_dir() else [])
    items: list[QueueItem] = []
    for path in paths:
        if path.is_file():
            items.extend(read_queue_file(path))
    return tuple(items)
