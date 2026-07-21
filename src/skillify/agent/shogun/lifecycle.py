"""One-active-team lifecycle boundary around the external Shogun process tree."""

from __future__ import annotations

import json
import os
import signal
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


_TEAM_HANDLE_REQUIRED_KEYS = {"session", "run_dir"}
_TEAM_HANDLE_OPTIONAL_KEYS = {"team_id", "base_commit"}


@dataclass(frozen=True)
class TeamHandle:
    session: str
    run_dir: Path
    team_id: str | None = None
    base_commit: str | None = None

    def to_dict(self) -> dict[str, str]:
        value = {"session": self.session, "run_dir": str(self.run_dir)}
        if self.team_id is not None:
            value["team_id"] = self.team_id
        if self.base_commit is not None:
            value["base_commit"] = self.base_commit
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TeamHandle":
        keys = set(value)
        if not _TEAM_HANDLE_REQUIRED_KEYS <= keys <= (
            _TEAM_HANDLE_REQUIRED_KEYS | _TEAM_HANDLE_OPTIONAL_KEYS
        ):
            raise ValueError("Shogun team handle has unexpected fields")
        session, run_dir = value["session"], value["run_dir"]
        if not isinstance(session, str) or not session or not isinstance(run_dir, str):
            raise ValueError("Shogun team handle is invalid")
        path = Path(run_dir)
        if not path.is_absolute():
            raise ValueError("Shogun team run directory must be absolute")
        team_id = value.get("team_id")
        if team_id is not None and not isinstance(team_id, str):
            raise ValueError("Shogun team handle is invalid")
        base_commit = value.get("base_commit")
        if base_commit is not None and not isinstance(base_commit, str):
            raise ValueError("Shogun team handle is invalid")
        return cls(session, path, team_id, base_commit)

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

    @staticmethod
    def process_environment(environment: Mapping[str, str]) -> dict[str, str]:
        inherited = {
            name: value for name, value in os.environ.items()
            if name in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "SHELL", "TMPDIR"}
        }
        inherited.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
        inherited.setdefault("LANG", "C.UTF-8")
        inherited.setdefault("TERM", "xterm-256color")
        return {**inherited, **environment}

    def start(
        self, command: Sequence[str], *, cwd: Path, environment: Mapping[str, str],
    ) -> TeamHandle:
        # Only explicitly public process settings are inherited. In particular,
        # API keys from the Bridge environment must never reach the tmux server.
        env = self.process_environment(environment)
        process = subprocess.Popen(
            tuple(command), cwd=str(cwd), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.starters.append(process)
        handle = TeamHandle("shogun", Path(cwd).resolve())
        # The approved upstream entrypoint has its own 30-second CLI readiness
        # probe before it starts watchers and exits. Leave enough headroom for
        # that probe plus the remaining setup on slower endpoint VMs.
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            exit_code = process.poll()
            if exit_code == 0 and self.is_alive(handle):
                return handle
            if exit_code not in (None, 0):
                break
            time.sleep(0.1)
        self.terminate(handle)
        self.cleanup_processes(handle)
        raise ShogunLifecycleError("Shogun tmux session did not become ready")

    def is_alive(self, handle: TeamHandle) -> bool:
        for session in (handle.session, "multiagent"):
            result = subprocess.run(
                ("tmux", "has-session", "-t", session), check=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if result.returncode != 0:
                return False
        return True

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
        self._terminate_run_dir_processes(handle.run_dir)
        for path in Path("/tmp").glob("shogun_*"):
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)

    @staticmethod
    def _processes_in_run_dir(run_dir: Path) -> set[int]:
        root = run_dir.resolve()
        result = set()
        for path in Path("/proc").glob("[0-9]*/cwd"):
            try:
                cwd = path.resolve(strict=True)
                if cwd == root or root in cwd.parents:
                    result.add(int(path.parent.name))
            except (OSError, ValueError):
                continue
        return result

    def _terminate_run_dir_processes(self, run_dir: Path) -> None:
        pids = self._processes_in_run_dir(run_dir)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 2
        while pids and time.monotonic() < deadline:
            time.sleep(0.05)
            pids &= self._processes_in_run_dir(run_dir)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

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
            shutil.rmtree(generated.queue_dir.parent, ignore_errors=True)
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
