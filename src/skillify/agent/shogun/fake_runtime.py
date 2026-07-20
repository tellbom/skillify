"""Scriptable runtime used to exercise the adapter without tmux or real CLIs."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path

import yaml

from skillify.agent.shogun.lifecycle import TeamHandle


class FakeRuntime:
    def __init__(self, snapshots: Iterable[Mapping[str, object]] = ()) -> None:
        self.snapshots = tuple(dict(item) for item in snapshots)
        self.actions: list[tuple[str, object]] = []
        self.alive = False

    def start(
        self, command: Sequence[str], *, cwd: Path, environment: Mapping[str, str],
    ) -> TeamHandle:
        handle = TeamHandle("shogun", Path(cwd).resolve())
        self.alive = True
        self.actions.append(("start", {
            "command": tuple(command), "cwd": str(cwd),
            "environment_names": tuple(sorted(environment)),
        }))
        return handle

    def is_alive(self, handle: TeamHandle) -> bool:
        self.actions.append(("is-alive", handle.session))
        return self.alive

    def terminate(self, handle: TeamHandle) -> None:
        self.actions.append(("kill-session", handle.session))
        self.actions.append(("pkill", "watcher_supervisor.sh"))
        self.alive = False

    def cleanup_processes(self, handle: TeamHandle) -> None:
        self.actions.extend([
            ("kill-session", "multiagent"),
            ("pkill", "inbox_watcher.sh"),
            ("pkill", "ntfy_listener.sh"),
            ("clean-temp", "/tmp/shogun_*"),
        ])

    def queue_states(
        self, queue_dir: Path, handle: TeamHandle,
    ) -> Iterator[dict[str, object]]:
        self.actions.append(("queue-states", str(queue_dir)))
        for snapshot in self.snapshots:
            if not self.is_alive(handle):
                return
            self.write_snapshot(queue_dir, snapshot)
            yield dict(snapshot)

    def write_snapshot(self, queue_dir: Path, snapshot: Mapping[str, object]) -> None:
        for relative, value in snapshot.items():
            path = Path(queue_dir) / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        self.actions.append(("snapshot", tuple(sorted(snapshot))))
