"""P1-6: per-task cleanup (source/index removal), idempotent, isolated by task_id."""

from __future__ import annotations

import shutil
from pathlib import Path

from skillify.codemap.upload_verify import UploadVerifyError, validate_task_id


class TaskCleanupError(Exception):
    pass


def remove_task(tasks_root: Path, task_id: str) -> bool:
    """Delete a task's entire directory (source + index). Returns False if it never existed."""
    try:
        task_id = validate_task_id(task_id)
    except UploadVerifyError as exc:
        raise TaskCleanupError(str(exc)) from exc

    task_dir = Path(tasks_root) / task_id
    if not task_dir.exists():
        return False

    shutil.rmtree(task_dir)
    return True


def run() -> None:
    """Standalone Phase-1 entry: `python -m skillify.codemap.task_cleanup <task_id>`."""
    import os
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m skillify.codemap.task_cleanup <task_id>", file=sys.stderr)
        raise SystemExit(2)

    tasks_root = Path(os.environ.get("SKILLIFY_CODEMAP_TASKS_ROOT", "/srv/codemap/tasks"))
    deleted = remove_task(tasks_root, sys.argv[1])
    print("deleted" if deleted else "not-found")


if __name__ == "__main__":
    run()
