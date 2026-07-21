"""Tests for P1-6 per-task cleanup: source/index removal, idempotent, no cross-task leakage."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillify.codemap.task_cleanup import TaskCleanupError, remove_task


def test_remove_task_deletes_source_and_index(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "task-1"
    (task_dir / "source").mkdir(parents=True)
    (task_dir / "source" / "main.py").write_text("x=1\n", encoding="utf-8")
    (task_dir / "index").mkdir(parents=True)
    (task_dir / "index" / "data.bin").write_bytes(b"\x00\x01")

    deleted = remove_task(tasks_root, "task-1")

    assert deleted is True
    assert not task_dir.exists()


def test_remove_task_is_idempotent_on_missing_task(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    tasks_root.mkdir(parents=True)

    deleted = remove_task(tasks_root, "task-does-not-exist")

    assert deleted is False


def test_remove_task_rejects_invalid_task_id(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    with pytest.raises(TaskCleanupError):
        remove_task(tasks_root, "../escape")


def test_remove_task_does_not_touch_sibling_tasks(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    (tasks_root / "task-1" / "source").mkdir(parents=True)
    (tasks_root / "task-2" / "source").mkdir(parents=True)
    (tasks_root / "task-2" / "source" / "keep.py").write_text("keep\n", encoding="utf-8")

    remove_task(tasks_root, "task-1")

    assert not (tasks_root / "task-1").exists()
    assert (tasks_root / "task-2" / "source" / "keep.py").read_text(encoding="utf-8") == "keep\n"
