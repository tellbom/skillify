"""P1-4: per-task Docker index orchestrator (source :ro, index writable, internal/no-egress network).

Stdlib-only + `subprocess` (injectable, matching `GitNexusVisualizer`'s pattern
in `skillify.codemap.visualizer`), so this stays importable/testable without
Docker or a Linux host. Does not itself validate "no egress" — that is a
property of the `network` the caller passes in (see P1-1's offline image and
the existing `internal: true` Docker network already provisioned for GitNexus).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from skillify.codemap.upload_verify import UploadVerifyError, validate_task_id


class IndexError(Exception):  # noqa: A001 - deliberately shadows builtin; matches domain vocabulary
    pass


@dataclass
class IndexResult:
    task_id: str
    source_dir: Path
    index_dir: Path
    command: list[str] = field(repr=False)


class IndexOrchestrator:
    def __init__(
        self,
        *,
        tasks_root: Path,
        image: str,
        network: str,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        timeout: float = 900.0,
    ) -> None:
        self.tasks_root = Path(tasks_root)
        self.image = image
        self.network = network
        self._run = run
        self.timeout = timeout

    def index(self, task_id: str) -> IndexResult:
        try:
            task_id = validate_task_id(task_id)
        except UploadVerifyError as exc:
            raise IndexError(str(exc)) from exc

        source_dir = self.tasks_root / task_id / "source"
        if not source_dir.is_dir():
            raise IndexError(f"source directory does not exist for task {task_id}: {source_dir}")

        index_dir = self.tasks_root / task_id / "index"
        index_dir.mkdir(parents=True, exist_ok=True)

        command = [
            "docker", "run", "--rm",
            "--network", self.network,
            "-v", f"{source_dir}:/workspace:ro",
            "-v", f"{index_dir}:/workspace/.gitnexus",
            "-w", "/workspace",
            self.image,
            "analyze", "--skip-git", "--index-only", "--skip-skills", "--skip-agents-md", "--no-stats",
        ]
        result = self._run(command, capture_output=True, text=True, timeout=self.timeout)
        if result.returncode != 0:
            detail = (result.stderr or "").strip()[:500]
            raise IndexError(f"gitnexus index failed for task {task_id}: {detail}")

        if not any(index_dir.iterdir()):
            raise IndexError(f"gitnexus did not produce an index for task {task_id}")

        return IndexResult(task_id=task_id, source_dir=source_dir, index_dir=index_dir, command=command)


def run() -> None:
    """Standalone Phase-1 entry: `python -m skillify.codemap.index_orchestrator <task_id>`."""
    import json
    import os
    import sys
    from dataclasses import asdict

    if len(sys.argv) != 2:
        print("usage: python -m skillify.codemap.index_orchestrator <task_id>", file=sys.stderr)
        raise SystemExit(2)

    orchestrator = IndexOrchestrator(
        tasks_root=Path(os.environ.get("SKILLIFY_CODEMAP_TASKS_ROOT", "/srv/codemap/tasks")),
        image=os.environ.get("SKILLIFY_CODEMAP_IMAGE", "skillify/gitnexus:1.6.9"),
        network=os.environ.get("SKILLIFY_CODEMAP_NETWORK", "skillify-gitnexus-offline"),
    )
    result = orchestrator.index(sys.argv[1])
    print(json.dumps(asdict(result), default=str, sort_keys=True))


if __name__ == "__main__":
    run()
