"""One-active-team lifecycle boundary around the external Shogun process tree."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from skillify.agent.shogun.config_gen import GeneratedShogunConfig


class ShogunLifecycleError(RuntimeError):
    pass


class RuntimeControl(Protocol):
    def start(self, command: Sequence[str], *, cwd: Path, environment: Mapping[str, str]) -> int: ...
    def terminate(self, pid: int) -> None: ...
    def cleanup_processes(self) -> None: ...
    def queue_states(self, queue_dir: Path) -> Iterator[dict[str, object]]: ...


class ProcessRuntime:
    """Real process boundary. Its behavior is accepted only in the test environment."""

    def __init__(self) -> None:
        self.processes: dict[int, subprocess.Popen[bytes]] = {}

    def start(
        self, command: Sequence[str], *, cwd: Path, environment: Mapping[str, str],
    ) -> int:
        env = {**os.environ, **environment}
        process = subprocess.Popen(
            tuple(command), cwd=str(cwd), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.processes[process.pid] = process
        return process.pid

    def terminate(self, pid: int) -> None:
        process = self.processes.pop(pid, None)
        if process is not None and process.poll() is None:
            process.terminate()

    def _run(self, *command: str) -> None:
        subprocess.run(command, check=False, capture_output=True, timeout=5)

    def cleanup_processes(self) -> None:
        self._run("tmux", "kill-session", "-t", "shogun")
        self._run("tmux", "kill-session", "-t", "multiagent")
        self._run("pkill", "-f", "watcher_supervisor.sh")
        self._run("pkill", "-f", "inbox_watcher.sh")
        self._run("pkill", "-f", "ntfy_listener.sh")
        for path in Path("/tmp").glob("shogun_*"):
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)

    def queue_states(self, queue_dir: Path) -> Iterator[dict[str, object]]:
        while any(process.poll() is None for process in self.processes.values()):
            yield {}
            time.sleep(0.5)


@dataclass(frozen=True)
class ActiveTeam:
    task_id: str
    pid: int
    run_dir: Path
    queue_dir: Path
    guard_path: Path


class ShogunLifecycle:
    def __init__(self, runtime: RuntimeControl, guard_path: Path) -> None:
        self.runtime = runtime
        self.guard_path = Path(guard_path)
        self.active: ActiveTeam | None = None

    def start(
        self, task_id: str, generated: GeneratedShogunConfig, *, install_root: Path,
    ) -> ActiveTeam:
        if self.active is not None or self.guard_path.exists():
            raise ShogunLifecycleError("another Shogun team is already active on this endpoint")
        self.guard_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(self.guard_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ShogunLifecycleError("another Shogun team is already active on this endpoint") from exc
        try:
            os.write(descriptor, task_id.encode("utf-8"))
        finally:
            os.close(descriptor)
        try:
            pid = self.runtime.start(
                generated.command, cwd=Path(install_root), environment=generated.environment,
            )
        except Exception:
            self.guard_path.unlink(missing_ok=True)
            raise
        self.active = ActiveTeam(
            task_id, pid, generated.queue_dir.parent, generated.queue_dir, self.guard_path,
        )
        return self.active

    def cancel(self, team: ActiveTeam) -> None:
        self.runtime.terminate(team.pid)
        self.runtime.cleanup_processes()
        self._release(team)

    def stop(self, team: ActiveTeam) -> None:
        self.runtime.terminate(team.pid)
        self.runtime.cleanup_processes()
        self._release(team)

    def _release(self, team: ActiveTeam) -> None:
        team.guard_path.unlink(missing_ok=True)
        if team.run_dir.is_dir():
            shutil.rmtree(team.run_dir)
        if self.active == team:
            self.active = None
