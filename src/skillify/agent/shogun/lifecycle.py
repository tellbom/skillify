"""One-active-team lifecycle boundary around the external Shogun process tree."""

from __future__ import annotations

import json
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
    def start(
        self, command: Sequence[str], *, cwd: Path, environment: Mapping[str, str],
    ) -> "TeamHandle": ...
    def is_alive(self, handle: "TeamHandle") -> bool: ...
    def terminate(self, handle: "TeamHandle") -> None: ...
    def cleanup_processes(self, handle: "TeamHandle") -> None: ...
    def queue_states(
        self, queue_dir: Path, handle: "TeamHandle",
    ) -> Iterator[dict[str, object]]: ...


@dataclass(frozen=True)
class TeamHandle:
    session: str
    run_dir: Path

    def to_dict(self) -> dict[str, str]:
        return {"session": self.session, "run_dir": str(self.run_dir)}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TeamHandle":
        if set(value) != {"session", "run_dir"}:
            raise ValueError("Shogun team handle has unexpected fields")
        session, run_dir = value["session"], value["run_dir"]
        if not isinstance(session, str) or not session or not isinstance(run_dir, str):
            raise ValueError("Shogun team handle is invalid")
        path = Path(run_dir)
        if not path.is_absolute():
            raise ValueError("Shogun team run directory must be absolute")
        return cls(session, path)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.to_dict(), sort_keys=True), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)

    @classmethod
    def read(cls, path: Path) -> "TeamHandle":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Shogun team handle must be an object")
        return cls.from_dict(value)


class ProcessRuntime:
    """Real process boundary. Its behavior is accepted only in the test environment."""

    def __init__(self) -> None:
        self.starters: list[subprocess.Popen[bytes]] = []

    def start(
        self, command: Sequence[str], *, cwd: Path, environment: Mapping[str, str],
    ) -> TeamHandle:
        # Only explicitly public process settings are inherited. In particular,
        # API keys from the Bridge environment must never reach the tmux server.
        inherited = {
            name: value for name, value in os.environ.items()
            if name in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "SHELL", "TMPDIR"}
        }
        env = {**inherited, **environment}
        process = subprocess.Popen(
            tuple(command), cwd=str(cwd), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.starters.append(process)
        handle = TeamHandle("shogun", Path(cwd).resolve())
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.is_alive(handle):
                return handle
            if process.poll() not in (None, 0):
                break
            time.sleep(0.1)
        self.terminate(handle)
        self.cleanup_processes(handle)
        raise ShogunLifecycleError("Shogun tmux session did not become ready")

    def is_alive(self, handle: TeamHandle) -> bool:
        result = subprocess.run(
            ("tmux", "has-session", "-t", handle.session), check=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0

    def terminate(self, handle: TeamHandle) -> None:
        # Stop a possible supervisor first so it cannot recreate watchers.
        scripts = handle.run_dir / "scripts"
        for name in ("watcher_supervisor.sh", "inbox_watcher.sh", "ntfy_listener.sh"):
            self._run("pkill", "-f", "--", str(scripts / name))
        self._run("tmux", "kill-session", "-t", handle.session)
        # Upstream hard-codes a second fixed session. The active-team guard makes
        # this targeted enough for the supported one-team-per-endpoint model.
        self._run("tmux", "kill-session", "-t", "multiagent")

    def _run(self, *command: str) -> None:
        subprocess.run(command, check=False, capture_output=True, timeout=5)

    def cleanup_processes(self, handle: TeamHandle) -> None:
        for path in Path("/tmp").glob("shogun_*"):
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)

    def queue_states(
        self, queue_dir: Path, handle: TeamHandle,
    ) -> Iterator[dict[str, object]]:
        while self.is_alive(handle):
            yield {}
            time.sleep(0.5)


@dataclass(frozen=True)
class ActiveTeam:
    task_id: str
    handle: TeamHandle
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
            handle = self.runtime.start(
                generated.command, cwd=generated.queue_dir.parent,
                environment=generated.environment,
            )
        except Exception:
            self.guard_path.unlink(missing_ok=True)
            raise
        self.active = ActiveTeam(
            task_id, handle, generated.queue_dir.parent, generated.queue_dir, self.guard_path,
        )
        return self.active

    def cancel(self, team: ActiveTeam) -> None:
        self.runtime.terminate(team.handle)
        self.runtime.cleanup_processes(team.handle)
        self._release(team)

    def stop(self, team: ActiveTeam) -> None:
        self.runtime.terminate(team.handle)
        self.runtime.cleanup_processes(team.handle)
        self._release(team)

    def _release(self, team: ActiveTeam) -> None:
        team.guard_path.unlink(missing_ok=True)
        if team.run_dir.is_dir():
            shutil.rmtree(team.run_dir)
        if self.active == team:
            self.active = None
