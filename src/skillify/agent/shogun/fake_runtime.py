"""Scriptable runtime used to exercise the adapter without tmux or real CLIs."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path

import yaml


class FakeRuntime:
    def __init__(self, snapshots: Iterable[Mapping[str, object]] = ()) -> None:
        self.snapshots = tuple(dict(item) for item in snapshots)
        self.actions: list[tuple[str, object]] = []
        self._next_pid = 1000

    def start(
        self, command: Sequence[str], *, cwd: Path, environment: Mapping[str, str],
    ) -> int:
        self._next_pid += 1
        self.actions.append(("start", {
            "command": tuple(command), "cwd": str(cwd),
            "environment_names": tuple(sorted(environment)),
        }))
        return self._next_pid

    def terminate(self, pid: int) -> None:
        self.actions.append(("terminate", pid))

    def cleanup_processes(self) -> None:
        self.actions.extend([
            ("kill-session", "shogun"),
            ("kill-session", "multiagent"),
            ("pkill", "watcher_supervisor.sh"),
            ("pkill", "inbox_watcher.sh"),
            ("pkill", "ntfy_listener.sh"),
            ("clean-temp", "/tmp/shogun_*"),
        ])

    def queue_states(self, queue_dir: Path) -> Iterator[dict[str, object]]:
        for snapshot in self.snapshots:
            self.write_snapshot(queue_dir, snapshot)
            yield dict(snapshot)

    def write_snapshot(self, queue_dir: Path, snapshot: Mapping[str, object]) -> None:
        for relative, value in snapshot.items():
            path = Path(queue_dir) / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        self.actions.append(("snapshot", tuple(sorted(snapshot))))
